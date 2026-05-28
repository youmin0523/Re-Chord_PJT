import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link2, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";

export function UrlInput({ onSubmit, disabled }) {
  const { t } = useTranslation();
  const [val, setVal] = useState("");
  const isUrl = /^https?:\/\//i.test(val.trim());

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (isUrl && !disabled) onSubmit(val.trim());
      }}
      className="glass rounded-2xl p-2.5 flex items-center gap-2"
    >
      <span className="pl-2 text-fg-muted">
        <Link2 className="size-5" />
      </span>
      <input
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder={t("submit.url_placeholder")}
        disabled={disabled}
        className="flex-1 bg-transparent text-sm placeholder:text-fg-muted/70 focus:outline-none"
      />
      <motion.button
        type="submit"
        whileHover={isUrl ? { scale: 1.03 } : undefined}
        whileTap={isUrl ? { scale: 0.97 } : undefined}
        disabled={!isUrl || disabled}
        className="inline-flex items-center gap-1.5 rounded-full h-9 px-4 text-sm font-medium bg-gradient-to-br from-violet to-magenta text-white disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {t("submit.url_cta")} <ArrowRight className="size-4" />
      </motion.button>
    </form>
  );
}
