"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
          code: ({ className, children, ...props }: any) => {
            const isBlock = /language-/.test(className || "");
            return isBlock ? (
              <code className={className} {...props}>{children}</code>
            ) : (
              <code className="px-1.5 py-0.5 rounded bg-accent/15 text-accent2 font-mono text-[0.85em] font-medium" {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
