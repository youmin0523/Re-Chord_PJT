import { useEffect, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Loader2, AlertTriangle, ArrowLeft } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { getLegalDoc } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Legal document viewer — renders ``docs/legal/{terms,privacy,copyright}.md``
 * fetched from the backend ``/legal/{id}`` endpoint. SignupConsent links
 * here so users can review terms before agreeing.
 *
 * Single source of truth: the markdown file. No copy/paste duplication
 * into JSX so policy revisions only need to touch one place.
 */

const VALID_DOCS = new Set(["terms", "privacy", "copyright", "consent"]);

const MD_COMPONENTS = {
  h1: (p) => <h1 className="text-2xl sm:text-3xl font-bold mt-6 mb-3 text-fg" {...p} />,
  h2: (p) => <h2 className="text-xl font-semibold mt-6 mb-2 text-fg border-b border-white/10 pb-1" {...p} />,
  h3: (p) => <h3 className="text-base font-semibold mt-4 mb-1.5 text-fg" {...p} />,
  p:  (p) => <p className="my-2 leading-relaxed text-fg-muted break-keep" {...p} />,
  ul: (p) => <ul className="list-disc pl-5 my-2 space-y-1" {...p} />,
  ol: (p) => <ol className="list-decimal pl-5 my-2 space-y-1" {...p} />,
  li: (p) => <li className="text-fg-muted leading-relaxed" {...p} />,
  a:  (p) => (
    <a
      {...p}
      target={p.href?.startsWith("http") ? "_blank" : undefined}
      rel={p.href?.startsWith("http") ? "noopener noreferrer" : undefined}
      className="text-cyan-300 underline-offset-2 hover:underline"
    />
  ),
  table: (p) => (
    <div className="my-3 overflow-x-auto">
      <table className="text-xs border-collapse w-full" {...p} />
    </div>
  ),
  th: (p) => <th className="border border-white/10 px-2 py-1 text-left font-semibold bg-white/5" {...p} />,
  td: (p) => <td className="border border-white/10 px-2 py-1" {...p} />,
  blockquote: (p) => (
    <blockquote
      className="border-l-4 border-violet/40 pl-3 my-3 text-fg-muted bg-white/[0.02] py-1"
      {...p}
    />
  ),
  code: ({ inline, children, ...rest }) =>
    inline ? (
      <code className="px-1 py-0.5 rounded bg-white/10 text-[0.9em] mono" {...rest}>{children}</code>
    ) : (
      <code className="block" {...rest}>{children}</code>
    ),
  pre: (p) => (
    <pre
      className="my-3 p-3 rounded-lg bg-black/35 ring-1 ring-white/10 overflow-x-auto text-[12px] mono"
      {...p}
    />
  ),
  hr: () => <hr className="my-5 border-white/10" />,
};

export default function LegalDoc() {
  const { docId } = useParams();
  const [content, setContent] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!VALID_DOCS.has(docId)) return;
    setContent(null);
    setError(null);
    getLegalDoc(docId)
      .then((r) => { if (!cancelled) setContent(r.markdown || ""); })
      .catch((e) => { if (!cancelled) setError(e?.message || String(e)); });
    return () => { cancelled = true; };
  }, [docId]);

  if (!VALID_DOCS.has(docId)) {
    return <Navigate to="/" replace />;
  }

  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12 pb-24">
      <a
        href="/"
        className="inline-flex items-center gap-1 text-[12px] text-fg-muted hover:text-fg mb-4"
      >
        <ArrowLeft className="size-3" /> 홈으로
      </a>

      {error ? (
        <div className={cn(
          "flex items-start gap-2 px-4 py-3 rounded-xl",
          "bg-rose-500/10 ring-1 ring-rose-500/30 text-rose-200",
        )}>
          <AlertTriangle className="size-4 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-semibold">문서를 불러오지 못했습니다</div>
            <div className="text-[11px] text-rose-300/80 mt-1">{error}</div>
          </div>
        </div>
      ) : content == null ? (
        <div className="flex items-center gap-2 text-fg-muted text-sm py-12">
          <Loader2 className="size-4 animate-spin" /> 문서를 불러오는 중…
        </div>
      ) : (
        <motion.article
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="prose-none"
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeSanitize]}
            components={MD_COMPONENTS}
          >
            {content}
          </ReactMarkdown>
        </motion.article>
      )}
    </main>
  );
}
