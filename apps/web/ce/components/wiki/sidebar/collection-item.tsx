/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { Lock, MoreHorizontal, Pencil, Plus, Trash2, Users } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { IconButton } from "@plane/propel/icon-button";
import { ChevronRightIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { CustomMenu } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useUser, useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
// plane web
import { WorkspacePageStore } from "@/plane-web/store/wiki/workspace-page.store";
import type { TWikiCollection } from "@/plane-web/types/wiki";
import { WIKI_ACCESS } from "@/plane-web/types/wiki";
import { CollectionDeleteModal } from "../modals/collection-delete-modal";
import { CollectionFormModal } from "../modals/collection-form-modal";
import { CollectionMembersModal } from "../modals/collection-members-modal";
import type { TWikiDragData } from "./page-tree-item";
import { WikiPageTreeItem } from "./page-tree-item";

type Props = {
  collection: TWikiCollection;
  activePageId?: string;
};

export const WikiCollectionItem = observer(function WikiCollectionItem(props: Props) {
  const { collection, activePageId } = props;
  const { workspaceSlug } = useParams();
  const router = useAppRouter();
  const { t } = useTranslation();
  const store = usePageStore(EPageStoreType.WORKSPACE);
  const { data: currentUser } = useUser();
  const { getWorkspaceRoleByWorkspaceSlug } = useUserPermissions();
  // state
  const [isOpen, setIsOpen] = useState(true);
  const [isDropTarget, setIsDropTarget] = useState(false);
  const [modal, setModal] = useState<"edit" | "delete" | "members" | undefined>(undefined);
  const headerRef = useRef<HTMLDivElement | null>(null);
  // derived
  const slug = workspaceSlug?.toString() ?? "";
  const rootIds = store.getRootPageIds(collection.id);
  const canEdit = (collection.current_user_access ?? -1) >= WIKI_ACCESS.EDIT;
  const isAdmin = getWorkspaceRoleByWorkspaceSlug(slug) === EUserPermissions.ADMIN;
  const isOwner = collection.owned_by_id === currentUser?.id;
  const canManage = isOwner || (isAdmin && collection.access === 0);
  const name = collection.is_default ? t("wiki_collections.predefined.general") : collection.name;

  useEffect(() => {
    const element = headerRef.current;
    if (!element) return;
    return dropTargetForElements({
      element,
      canDrop: ({ source }) => (source.data as TWikiDragData)?.type === "wiki-page" && canEdit,
      onDragEnter: () => setIsDropTarget(true),
      onDragLeave: () => setIsDropTarget(false),
      onDrop: ({ source }) => {
        setIsDropTarget(false);
        const last = rootIds.at(-1);
        store
          .moveWikiPage(slug, (source.data as TWikiDragData).id, {
            collection_id: collection.id,
            sort_order: WorkspacePageStore.between(last ? store.getPageById(last)?.sort_order : undefined, undefined),
          })
          .then(() => setIsOpen(true))
          .catch(() =>
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("toast.error"),
              message: t("workspace_wiki.toasts.move_error"),
            })
          );
      },
    });
  }, [canEdit, collection.id, rootIds, slug, store, t]);

  const handleCreatePage = async () => {
    try {
      const page = await store.createWikiPage(slug, { name: "", collection_id: collection.id });
      setIsOpen(true);
      if (page?.id) router.push(`/${slug}/wiki/${page.id}`);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("toast.error"),
        message: t("wiki_collections.toasts.create_page_in_collection_error"),
      });
    }
  };

  return (
    <div className="flex flex-col">
      <CollectionFormModal isOpen={modal === "edit"} onClose={() => setModal(undefined)} collection={collection} />
      <CollectionDeleteModal isOpen={modal === "delete"} onClose={() => setModal(undefined)} collection={collection} />
      <CollectionMembersModal
        isOpen={modal === "members"}
        onClose={() => setModal(undefined)}
        collection={collection}
        canManage={canManage}
      />
      <div
        ref={headerRef}
        className={cn(
          "group/wiki-collection flex w-full items-center gap-1 rounded-md px-1 py-1 text-12 font-semibold text-tertiary hover:bg-layer-transparent-hover",
          { "bg-layer-transparent-active ring-1 ring-accent-strong": isDropTarget }
        )}
      >
        <button
          type="button"
          className="flex min-w-0 flex-grow items-center gap-1 text-left"
          onClick={() => setIsOpen((open) => !open)}
        >
          <ChevronRightIcon className={cn("size-3 flex-shrink-0 transition-transform", { "rotate-90": isOpen })} />
          <span className="truncate uppercase">{name}</span>
          {collection.access === 1 && (
            <Lock className="size-3 flex-shrink-0" aria-label={t("wiki_collections.list.invite_only")} />
          )}
        </button>
        <div className="flex items-center opacity-0 group-hover/wiki-collection:opacity-100">
          {canEdit && (
            <IconButton
              variant="ghost"
              size="sm"
              icon={Plus}
              onClick={handleCreatePage}
              aria-label={t("wiki_collections.menu.create_new_page")}
              className="text-placeholder"
            />
          )}
          {!collection.is_default && (
            <CustomMenu
              customButton={<IconButton variant="ghost" size="sm" icon={MoreHorizontal} className="text-placeholder" />}
              placement="bottom-start"
              closeOnSelect
              ariaLabel={t("wiki_collections.menu.collection_options")}
            >
              {canManage && (
                <CustomMenu.MenuItem onClick={() => setModal("edit")}>
                  <span className="flex items-center gap-2">
                    <Pencil className="size-3.5" />
                    {t("wiki_collections.menu.edit_collection")}
                  </span>
                </CustomMenu.MenuItem>
              )}
              <CustomMenu.MenuItem onClick={() => setModal("members")}>
                <span className="flex items-center gap-2">
                  <Users className="size-3.5" />
                  {t("common.members")}
                </span>
              </CustomMenu.MenuItem>
              {canManage && (
                <CustomMenu.MenuItem onClick={() => setModal("delete")}>
                  <span className="flex items-center gap-2 text-danger-primary">
                    <Trash2 className="size-3.5" />
                    {t("wiki_collections.delete_modal.submit")}
                  </span>
                </CustomMenu.MenuItem>
              )}
            </CustomMenu>
          )}
        </div>
      </div>
      {isOpen && (
        <div className="flex flex-col">
          {rootIds.length === 0 ? (
            <p className="py-1 pl-6 text-12 text-placeholder">{t("wiki_collections.list.no_pages_title")}</p>
          ) : (
            rootIds.map((pageId) => (
              <WikiPageTreeItem key={pageId} pageId={pageId} depth={0} activePageId={activePageId} />
            ))
          )}
        </div>
      )}
    </div>
  );
});
