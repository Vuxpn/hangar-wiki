/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { FolderPlus, RotateCcw, SquarePen, Trash2 } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { IconButton } from "@plane/propel/icon-button";
import { ArchiveIcon, ChevronRightIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { cn, getPageName } from "@plane/utils";
// components
import { DeletePageModal } from "@/components/pages/modals/delete-page-modal";
import { SidebarWrapper } from "@/components/sidebar/sidebar-wrapper";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useAppRouter } from "@/hooks/use-app-router";
// plane web
import { CollectionFormModal } from "../modals/collection-form-modal";
import { WikiCollectionItem } from "./collection-item";

const storeType = EPageStoreType.WORKSPACE;

const WikiArchivedSection = observer(function WikiArchivedSection() {
  const { workspaceSlug, pageId: activePageId } = useParams();
  const router = useAppRouter();
  const { t } = useTranslation();
  const store = usePageStore(storeType);
  const [isOpen, setIsOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | undefined>(undefined);
  const archivedIds = store.getArchivedPageIds();
  const deleting = deletingId ? store.getPageById(deletingId) : undefined;

  if (archivedIds.length === 0) return null;

  return (
    <div className="flex flex-col">
      {deleting && (
        <DeletePageModal isOpen onClose={() => setDeletingId(undefined)} page={deleting} storeType={storeType} />
      )}
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex items-center gap-1 rounded-md px-1 py-1 text-12 font-semibold text-tertiary uppercase hover:bg-layer-transparent-hover"
      >
        <ChevronRightIcon className={cn("size-3 transition-transform", { "rotate-90": isOpen })} />
        <ArchiveIcon className="size-3" />
        {t("archives")}
        <span className="font-normal ml-auto">{archivedIds.length}</span>
      </button>
      {isOpen &&
        archivedIds.map((id) => {
          const page = store.getPageById(id);
          if (!page) return null;
          return (
            <div
              key={id}
              className={cn(
                "group/wiki-archived flex items-center gap-1 rounded-md py-1 pr-1 pl-5 text-13 text-tertiary hover:bg-layer-transparent-hover",
                { "bg-layer-transparent-active text-primary": activePageId === id }
              )}
            >
              <button
                type="button"
                className="min-w-0 flex-grow truncate text-left"
                onClick={() => router.push(`/${workspaceSlug}/wiki/${id}`)}
              >
                {getPageName(page.name)}
              </button>
              <div className="flex opacity-0 group-hover/wiki-archived:opacity-100">
                {page.canCurrentUserArchivePage && (
                  <IconButton
                    variant="ghost"
                    size="sm"
                    icon={RotateCcw}
                    aria-label={t("common.actions.restore")}
                    onClick={() =>
                      page
                        .restore({ shouldSync: true })
                        .then(() => store.fetchPagesList(workspaceSlug?.toString() ?? ""))
                        .catch(() =>
                          setToast({
                            type: TOAST_TYPE.ERROR,
                            title: t("toast.error"),
                            message: t("workspace_wiki.toasts.restore_error"),
                          })
                        )
                    }
                  />
                )}
                {page.canCurrentUserDeletePage && (
                  <IconButton
                    variant="ghost"
                    size="sm"
                    icon={Trash2}
                    aria-label={t("common.actions.delete")}
                    onClick={() => setDeletingId(id)}
                  />
                )}
              </div>
            </div>
          );
        })}
    </div>
  );
});

export const WikiSidebar = observer(function WikiSidebar() {
  const { workspaceSlug, pageId } = useParams();
  const router = useAppRouter();
  const { t } = useTranslation();
  const store = usePageStore(storeType);
  const [isCreatingCollection, setIsCreatingCollection] = useState(false);
  const slug = workspaceSlug?.toString() ?? "";

  const handleNewPage = async () => {
    try {
      const page = await store.createWikiPage(slug, {
        name: "",
        collection_id: store.defaultCollection?.id ?? null,
      });
      if (page?.id) router.push(`/${slug}/wiki/${page.id}`);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("toast.error"),
        message: t("wiki_collections.toasts.create_page_error"),
      });
    }
  };

  return (
    <SidebarWrapper
      title="Wiki"
      quickActions={
        <div className="flex items-center gap-2">
          {store.isCurrentUserWorkspaceMember && (
            <Button variant="secondary" size="sm" className="grow" prependIcon={<SquarePen />} onClick={handleNewPage}>
              {t("wiki_collections.header.add_page")}
            </Button>
          )}
          {store.isCurrentUserWorkspaceMember && (
            <IconButton
              variant="secondary"
              size="base"
              icon={FolderPlus}
              aria-label={t("wiki_collections.create_modal.title")}
              onClick={() => setIsCreatingCollection(true)}
            />
          )}
        </div>
      }
    >
      <CollectionFormModal isOpen={isCreatingCollection} onClose={() => setIsCreatingCollection(false)} />
      <div className="flex flex-col gap-3">
        {store.sortedCollections.map((collection) => (
          <WikiCollectionItem key={collection.id} collection={collection} activePageId={pageId?.toString()} />
        ))}
        <WikiArchivedSection />
      </div>
    </SidebarWrapper>
  );
});
