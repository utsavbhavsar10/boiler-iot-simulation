"""
evaluation/finetune_chronos.py
───────────────────────────────
Phase 7 (Optional) — Fine-tune Chronos on boiler/chimney domain data

Only run this IF Phase 6a shows MAPE > 15% on key sensors
OR Phase 6b shows median fault lead-time < 10 minutes.

Recommended GPU: T4 (Google Colab) or A100 (GCP Vertex AI Custom Training).
Expected training time: ~45 minutes on T4 for 10 epochs.

Usage:
    python -m evaluation.finetune_chronos \
        --dataset models/training_data/boiler_chronos_dataset_*.jsonl \
        --output models/chronos-boiler-finetuned \
        --epochs 10 \
        --lr 1e-4

After fine-tuning, set in .env:
    CHRONOS_MODEL=./models/chronos-boiler-finetuned
"""

import argparse
import json
import logging
import time
from pathlib import Path

import torch
from chronos import ChronosPipeline  # type: ignore
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


class BoilerTimeSeriesDataset(Dataset):
    """
    PyTorch Dataset that reads the JSONL file produced by dataset_prep.py
    and yields (context_tensor, target_tensor) pairs for Chronos training.
    """

    def __init__(
        self,
        jsonl_path: str,
        context_length: int = 128,
        prediction_length: int = 20,
    ):
        self.context_length    = context_length
        self.prediction_length = prediction_length
        self.samples: list[tuple[list[float], list[float]]] = []

        path = Path(jsonl_path)
        logger.info("Loading dataset from %s …", path)
        with open(path, encoding="utf-8") as fin:
            for line in fin:
                record = json.loads(line.strip())
                series = record["target"]
                # Sliding windows: step by prediction_length
                for start in range(
                    0,
                    len(series) - context_length - prediction_length,
                    prediction_length,
                ):
                    ctx = series[start: start + context_length]
                    tgt = series[start + context_length: start + context_length + prediction_length]
                    if len(ctx) == context_length and len(tgt) == prediction_length:
                        self.samples.append((ctx, tgt))

        logger.info("Dataset ready: %d training windows", len(self.samples))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        ctx, tgt = self.samples[idx]
        return (
            torch.tensor(ctx, dtype=torch.float32),
            torch.tensor(tgt, dtype=torch.float32),
        )


def finetune_chronos(
    dataset_path: str,
    output_dir: str = "./models/chronos-boiler-finetuned",
    base_model: str = "amazon/chronos-t5-small",
    epochs: int = 10,
    learning_rate: float = 1e-4,
    batch_size: int = 8,
    context_length: int = 128,
    prediction_length: int = 20,
) -> str:
    """
    Fine-tune chronos-t5-small on the boiler dataset.

    Args:
        dataset_path:     Path to JSONL file from dataset_prep.py
        output_dir:       Where to save the fine-tuned model
        base_model:       Hugging Face model ID to start from
        epochs:           Training epochs (10 recommended)
        learning_rate:    AdamW learning rate (1e-4 recommended)
        batch_size:       Training batch size (8 for T4)
        context_length:   Input context window length
        prediction_length: Forecast horizon

    Returns:
        Path to saved fine-tuned model directory.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Device: %s", device)

    logger.info("Loading base model: %s", base_model)
    pipeline = ChronosPipeline.from_pretrained(
        base_model,
        device_map=device,
        torch_dtype=torch.float32,
    )

    dataset = BoilerTimeSeriesDataset(
        dataset_path,
        context_length=context_length,
        prediction_length=prediction_length,
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    optimizer = AdamW(pipeline.model.parameters(), lr=learning_rate)

    logger.info(
        "Starting fine-tuning: %d epochs × %d batches × batch_size=%d",
        epochs, len(loader), batch_size,
    )

    for epoch in range(epochs):
        epoch_loss = 0.0
        epoch_start = time.time()

        for batch_ctx, batch_tgt in loader:
            batch_ctx = batch_ctx.to(device)
            batch_tgt = batch_tgt.to(device)

            try:
                loss = pipeline.train_step(context=batch_ctx, target=batch_tgt)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(pipeline.model.parameters(), max_norm=1.0)
                optimizer.step()
                optimizer.zero_grad()
                epoch_loss += loss.item()
            except Exception as exc:
                logger.warning("Batch error: %s", exc)
                optimizer.zero_grad()
                continue

        epoch_time = round(time.time() - epoch_start, 1)
        logger.info(
            "Epoch %d/%d — avg_loss=%.6f — time=%.1fs",
            epoch + 1, epochs, epoch_loss / max(len(loader), 1), epoch_time,
        )

    # Save fine-tuned model
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    pipeline.model.save_pretrained(str(out_path))
    logger.info("Fine-tuned model saved to %s", out_path)

    # Hint for next steps
    print(f"""
✅ Fine-tuning complete!

Next steps:
1. Set CHRONOS_MODEL=./{output_dir} in .env
2. Restart the API: uvicorn api.chatbot_api:app --reload
3. Re-run Phase 6 evaluation: python -m evaluation.chronos_eval
4. Compare MAPE and lead-time vs baseline.
""")
    return str(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune Chronos on boiler data")
    parser.add_argument("--dataset",  required=True, help="Path to JSONL training dataset")
    parser.add_argument("--output",   default="models/chronos-boiler-finetuned")
    parser.add_argument("--model",    default="amazon/chronos-t5-small")
    parser.add_argument("--epochs",   type=int,   default=10)
    parser.add_argument("--lr",       type=float, default=1e-4)
    parser.add_argument("--batch",    type=int,   default=8)
    args = parser.parse_args()

    finetune_chronos(
        dataset_path=args.dataset,
        output_dir=args.output,
        base_model=args.model,
        epochs=args.epochs,
        learning_rate=args.lr,
        batch_size=args.batch,
    )
