/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
// plane web
import type { TWikiCollection } from "@/plane-web/types/wiki";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  collection: TWikiCollection;
};

/**
 * Pages of a public collection either move to General or are archived there;
 * a private collection's pages are always archived and become private to their
 * authors, so they cannot surface outside the collection's members.
 */
export const CollectionDeleteModal = observer(function CollectionDeleteModal(props: Props) {
  const { isOpen, onClose, collection } = props;
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  const { deleteCollection } = usePageStore(EPageStoreType.WORKSPACE);
  const [archivePages, setArchivePages] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const isPrivate = collection.access === 1;

  const handleDelete = async () => {
    if (!workspaceSlug) return;
    setIsDeleting(true);
    try {
      await deleteCollection(workspaceSlug.toString(), collection.id, isPrivate || archivePages);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t("toast.success"),
        message:
          isPrivate || archivePages
            ? t("wiki_collections.toasts.deleted_with_pages")
            : t("wiki_collections.toasts.transferred_deleted"),
      });
      onClose();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("wiki_collections.toasts.delete_error") });
    } finally {
      setIsDeleting(false);
    }
  };

  const options = [
    { archive: false, title: t("workspace_wiki.delete.move_title"), hint: t("workspace_wiki.delete.move_hint") },
    { archive: true, title: t("workspace_wiki.delete.archive_title"), hint: t("workspace_wiki.delete.archive_hint") },
  ];

  return (
    <AlertModalCore
      isOpen={isOpen}
      handleClose={onClose}
      handleSubmit={handleDelete}
      isSubmitting={isDeleting}
      title={t("wiki_collections.delete_modal.title")}
      primaryButtonText={{
        loading: t("wiki_collections.delete_modal.submit"),
        default: t("wiki_collections.delete_modal.submit"),
      }}
      content={
        isPrivate ? (
          <span>{t("workspace_wiki.delete.private_hint")}</span>
        ) : (
          <span className="flex flex-col gap-2">
            {options.map((option) => (
              <button
                key={String(option.archive)}
                type="button"
                onClick={() => setArchivePages(option.archive)}
                className={cn(
                  "flex flex-col items-start rounded-md border px-3 py-2 text-left",
                  archivePages === option.archive ? "border-accent-strong" : "border-subtle"
                )}
              >
                <span className="text-13 font-medium text-primary">{option.title}</span>
                <span className="text-12 text-tertiary">{option.hint}</span>
              </button>
            ))}
          </span>
        )
      }
    />
  );
});
