import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { JobLibrary } from "@/components/JobLibrary";

/**
 * Full-page library — primarily for mobile, where the sidebar rail is hidden.
 * On desktop the sidebar usually suffices; this page is still useful for
 * keyboard / accessibility users who want the larger view.
 */
export default function LibraryPage() {
  const { t } = useTranslation();
  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10 lg:py-12">
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-2 mb-5 sm:mb-6"
      >
        <div className="text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">
          LIBRARY
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
          <span className="gradient-text">{t("library_page2.title")}</span>
        </h1>
        <p className="text-fg-muted text-sm max-w-xl">
          {t("library_page2.subtitle")}
        </p>
      </motion.div>

      <div className="glass rounded-2xl p-4 sm:p-6">
        <JobLibrary />
      </div>
    </main>
  );
}
