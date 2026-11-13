/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import { draggable, dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { attachInstruction, extractInstruction } from "@atlaskit/pragmatic-drag-and-drop-hitbox/tree-item";
import { MoreHorizontal, Plus } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { IconButton } from "@plane/propel/icon-button";
import { ArchiveIcon, ChevronRightIcon, LinkIcon, PageIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { InstructionType } from "@plane/types";
import { ControlLink, CustomMenu, DropIndicator } from "@plane/ui";
import { cn, copyUrlToClipboard, getPageName } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useAppRouter } from "@/hooks/use-app-router";
// plane web
import { WorkspacePageStore } from "@/plane-web/store/wiki/workspace-page.store";

export type TWikiDragData = { type: "wiki-page"; id: string };

type Props = {
  pageId: string;
  depth: number;
  activePageId?: string;
};

const INDENT = 12;

/** One page in the wiki tree, with its children below it when expanded. */
export const WikiPageTreeItem = observer(function WikiPageTreeItem(props: Props) {
  const { pageId, depth, activePageId } = props;
  const { workspaceSlug } = useParams();
  const router = useAppRouter();
  const { t } = useTranslation();
  const store = usePageStore(EPageStoreType.WORKSPACE);
  const page = store.getPageById(pageId);
  const childIds = store.getChildPageIds(pageId);
  const isAncestorOfActive = !!activePageId && store.getAncestorIds(activePageId).includes(pageId);
  // state
  const [isOpen, setIsOpen] = useState(isAncestorOfActive);
  const [isDragging, setIsDragging] = useState(false);
  const [instruction, setInstruction] = useState<InstructionType | undefined>(undefined);
  const rowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (isAncestorOfActive) setIsOpen(true);
  }, [isAncestorOfActive]);

  const canMove = !!page?.canCurrentUserMovePage;

  useEffect(() => {
    const element = rowRef.current;
    if (!element || !page) return;
    return combine(
      draggable({
        element,
        canDrag: () => canMove,
        getInitialData: (): TWikiDragData => ({ type: "wiki-page", id: pageId }),
        onDragStart: () => setIsDragging(true),
        onDrop: () => setIsDragging(false),
      }),
      dropTargetForElements({
        element,
        canDrop: ({ source }) => {
          const data = source.data as TWikiDragData;
          if (data?.type !== "wiki-page" || data.id === pageId) return false;
          // A page cannot go below itself.
          return !store.getAncestorIds(pageId).includes(data.id) && !!page.canCurrentUserEditPage;
        },
        getData: ({ input, element: el }) =>
          attachInstruction(
            { type: "wiki-page", id: pageId },
            { input, element: el, currentLevel: depth, indentPerLevel: INDENT, mode: "standard" }
          ),
        onDrag: ({ self }) => {
          const next = extractInstruction(self.data)?.type;
          setInstruction(next === "instruction-blocked" ? undefined : next);
        },
        onDragLeave: () => setInstruction(undefined),
        onDrop: ({ self, source }) => {
          setInstruction(undefined);
          const kind = extractInstruction(self.data)?.type;
          const sourceId = (source.data as TWikiDragData).id;
          if (!kind || kind === "instruction-blocked" || !workspaceSlug) return;
          void handleDrop(sourceId, kind);
        },
      })
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageId, depth, canMove]);

  if (!page) return null;

  const siblingIds = page.parent_id
    ? store.getChildPageIds(page.parent_id)
    : page.collection_id
      ? store.getRootPageIds(page.collection_id)
      : [];

  const handleDrop = async (sourceId: string, kind: InstructionType) => {
    const slug = workspaceSlug?.toString() ?? "";
    try {
      if (kind === "make-child") {
        const last = store.getChildPageIds(pageId).at(-1);
        await store.moveWikiPage(slug, sourceId, {
          parent_id: pageId,
          sort_order: WorkspacePageStore.between(last ? store.getPageById(last)?.sort_order : undefined, undefined),
        });
        setIsOpen(true);
        return;
      }
      const others = siblingIds.filter((id) => id !== sourceId);
      const index = others.indexOf(pageId);
      const neighbour = kind === "reorder-above" ? others[index - 1] : others[index + 1];
      const [before, after] =
        kind === "reorder-above"
          ? [neighbour ? store.getPageById(neighbour)?.sort_order : undefined, page.sort_order]
          : [page.sort_order, neighbour ? store.getPageById(neighbour)?.sort_order : undefined];
      const sortOrder = WorkspacePageStore.between(before, after);
      await store.moveWikiPage(
        slug,
        sourceId,
        page.parent_id
          ? { parent_id: page.parent_id, sort_order: sortOrder }
          : { collection_id: page.collection_id, sort_order: sortOrder }
      );
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("workspace_wiki.toasts.move_error") });
    }
  };

  const handleCreateChild = async () => {
    try {
      const child = await store.createWikiPage(workspaceSlug?.toString() ?? "", {
        name: "",
        parent_id: pageId,
        access: page.access,
      });
      setIsOpen(true);
      if (child?.id) router.push(`/${workspaceSlug}/wiki/${child.id}`);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("toast.error"),
        message: t("wiki_collections.toasts.create_page_error"),
      });
    }
  };

  const handleCopyLink = () =>
    copyUrlToClipboard(`${workspaceSlug}/wiki/${pageId}`).then(() =>
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t("toast.success"),
        message: t("wiki_collections.list.page_link_copied"),
      })
    );

  const handleArchive = async () => {
    try {
      await page.archive({ shouldSync: true });
      if (activePageId === pageId) router.push(`/${workspaceSlug}/wiki`);
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("workspace_wiki.toasts.archive_error") });
    }
  };

  const isActive = activePageId === pageId;
  const hasChildren = childIds.length > 0;

  return (
    <div className={cn({ "opacity-60": isDragging })}>
      <DropIndicator isVisible={instruction === "reorder-above"} />
      <div
        ref={rowRef}
        className={cn(
          "group/wiki-page relative flex w-full items-center gap-1 rounded-md py-1 pr-1 text-13 text-secondary hover:bg-layer-transparent-hover",
          {
            "bg-layer-transparent-active text-primary": isActive,
            "ring-1 ring-accent-strong": instruction === "make-child",
          }
        )}
        style={{ paddingLeft: `${4 + depth * INDENT}px` }}
      >
        <button
          type="button"
          className={cn("grid size-4 flex-shrink-0 place-items-center rounded-sm text-placeholder", {
            invisible: !hasChildren,
          })}
          onClick={() => setIsOpen((open) => !open)}
          aria-label={isOpen ? t("wiki_collections.list.collapse_page") : t("wiki_collections.list.expand_page")}
        >
          <ChevronRightIcon className={cn("size-3 transition-transform", { "rotate-90": isOpen })} />
        </button>
        <ControlLink
          href={`/${workspaceSlug}/wiki/${pageId}`}
          onClick={() => router.push(`/${workspaceSlug}/wiki/${pageId}`)}
          className="flex min-w-0 flex-grow items-center gap-1.5"
        >
          <span className="grid size-4 flex-shrink-0 place-items-center">
            {page.logo_props?.in_use ? (
              <Logo logo={page.logo_props} size={14} type="lucide" />
            ) : (
              <PageIcon className="size-3.5" />
            )}
          </span>
          <span className="truncate">{getPageName(page.name)}</span>
        </ControlLink>
        <div className="flex items-center opacity-0 group-hover/wiki-page:opacity-100">
          {page.canCurrentUserEditPage && (
            <IconButton
              variant="ghost"
              size="sm"
              icon={Plus}
              onClick={handleCreateChild}
              aria-label={t("workspace_wiki.sidebar.add_sub_page")}
              className="text-placeholder"
            />
          )}
          <CustomMenu
            customButton={<IconButton variant="ghost" size="sm" icon={MoreHorizontal} className="text-placeholder" />}
            placement="bottom-start"
            closeOnSelect
            ariaLabel={t("wiki_collections.list.page_actions")}
          >
            <CustomMenu.MenuItem onClick={handleCopyLink}>
              <span className="flex items-center gap-2">
                <LinkIcon className="size-3.5" />
                {t("common.actions.copy_link")}
              </span>
            </CustomMenu.MenuItem>
            {page.canCurrentUserArchivePage && (
              <CustomMenu.MenuItem onClick={handleArchive}>
                <span className="flex items-center gap-2">
                  <ArchiveIcon className="size-3.5" />
                  {t("common.actions.archive")}
                </span>
              </CustomMenu.MenuItem>
            )}
          </CustomMenu>
        </div>
      </div>
      <DropIndicator isVisible={instruction === "reorder-below"} />
      {isOpen &&
        childIds.map((childId) => (
          <WikiPageTreeItem key={childId} pageId={childId} depth={depth + 1} activePageId={activePageId} />
        ))}
    </div>
  );
});
