import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

function fallbackTitle(c, t) {
  if (c.title) return c.title;
  const preview = (c.last_preview || "").trim();
  if (preview) return preview.length > 32 ? preview.slice(0, 32) + "…" : preview;
  return t("chat.untitled_conversation");
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 p-2.5 border-b border-white/5">
        <button
          type="button"
          onClick={onNew}
          className="w-full inline-flex items-center justify-center gap-1.5 h-9 rounded-xl bg-gradient-to-br from-violet to-cyan text-white text-xs font-medium hover:brightness-110 transition shadow-[0_4px_16px_rgba(139,92,246,0.3)]"
        >
          <Plus className="size-3.5" />
          {t("chat.new_conversation")}
        </button>
      </div>
      <ul className="flex-1 min-h-0 overflow-y-auto py-1" role="listbox">
        {conversations.length === 0 && (
          <li className="px-3 py-4 text-[11px] text-fg-muted text-center">
            {t("chat.no_conversations")}
          </li>
        )}
        {conversations.map((c) => {
          const isActive = c.id === activeId;
          return (
            <li
              key={c.id}
              role="option"
              aria-selected={isActive}
              className={`group relative mx-1.5 my-0.5 rounded-lg cursor-pointer transition-colors ${
                isActive
                  ? "bg-violet/15 ring-1 ring-violet/30"
                  : "hover:bg-white/5"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                className="w-full text-left px-2.5 py-2 pr-7"
                title={fallbackTitle(c, t)}
              >
                <div className="text-[12px] text-fg font-medium truncate">
                  {fallbackTitle(c, t)}
                </div>
                {c.last_preview && (
                  <div className="text-[10px] text-fg-muted truncate mt-0.5">
                    {c.last_preview}
                  </div>
                )}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm(t("chat.delete_confirm"))) {
                    onDelete(c.id);
                  }
                }}
                title={t("chat.delete_conversation")}
                aria-label={t("chat.delete_conversation")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex items-center justify-center size-6 rounded-md text-fg-muted/70 hover:text-rose-300 hover:bg-rose-500/10 opacity-0 group-hover:opacity-100 focus:opacity-100 transition"
              >
                <Trash2 className="size-3" />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
