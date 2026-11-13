/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set, unset } from "lodash-es";
import { action, computed, makeObservable, observable, runInAction } from "mobx";
import { computedFn } from "mobx-utils";
// plane imports
import { EUserPermissions } from "@plane/constants";
import type { TPage, TPageFilters, TPageNavigationTabs } from "@plane/types";
import { filterPagesByPageType, getPageName, orderPages, shouldFilterPage } from "@plane/utils";
// store
import type { IProjectPageStore } from "@/store/pages/project-page.store";
import type { CoreRootStore } from "@/store/root.store";
// plane web
import { WikiService } from "@/plane-web/services/wiki.service";
import type { TWikiCollection, TWikiPage, TWikiPageMovePayload } from "@/plane-web/types/wiki";
import type { TWorkspacePage } from "./workspace-page";
import { WorkspacePage } from "./workspace-page";

type TLoader = "init-loader" | "mutation-loader" | undefined;

/**
 * The workspace wiki: its collections and every page the user may read.
 *
 * It keeps the project page store's shape so the shared editor components,
 * which reach the store through `usePageStore(storeType)`, work unchanged; the
 * project argument those methods take is ignored here.
 */
export interface IWorkspacePageStore extends Omit<
  IProjectPageStore,
  "data" | "getPageById" | "fetchPagesList" | "fetchPageDetails"
> {
  data: Record<string, TWorkspacePage>;
  fetchPagesList: (
    workspaceSlug: string,
    projectId?: string,
    pageType?: TPageNavigationTabs
  ) => Promise<TPage[] | undefined>;
  /** (slug, pageId) for the wiki; (slug, projectId, pageId) is accepted for project-shaped callers. */
  fetchPageDetails: (
    workspaceSlug: string,
    pageIdOrProjectId: string,
    pageId?: string,
    options?: { trackVisit?: boolean }
  ) => Promise<TPage | undefined>;
  collections: Record<string, TWikiCollection>;
  collectionsLoaded: boolean;
  getPageById: (pageId: string) => TWorkspacePage | undefined;
  // collections
  sortedCollections: TWikiCollection[];
  defaultCollection: TWikiCollection | undefined;
  getCollectionById: (collectionId: string) => TWikiCollection | undefined;
  fetchCollections: (workspaceSlug: string) => Promise<TWikiCollection[]>;
  createCollection: (workspaceSlug: string, data: Partial<TWikiCollection>) => Promise<TWikiCollection>;
  updateCollection: (
    workspaceSlug: string,
    collectionId: string,
    data: Partial<TWikiCollection>
  ) => Promise<TWikiCollection>;
  deleteCollection: (workspaceSlug: string, collectionId: string, archivePages: boolean) => Promise<void>;
  // tree
  getRootPageIds: (collectionId: string, archived?: boolean) => string[];
  getChildPageIds: (pageId: string, archived?: boolean) => string[];
  getAncestorIds: (pageId: string) => string[];
  getArchivedPageIds: () => string[];
  addPageToStore: (page: TWikiPage) => TWorkspacePage | undefined;
  createWikiPage: (
    workspaceSlug: string,
    data: Partial<TPage> & { parent_id?: string | null; collection_id?: string | null }
  ) => Promise<TWorkspacePage | undefined>;
  moveWikiPage: (workspaceSlug: string, pageId: string, payload: TWikiPageMovePayload) => Promise<void>;
  isCurrentUserWorkspaceMember: boolean;
}

const SORT_STEP = 10000;

export class WorkspacePageStore implements IWorkspacePageStore {
  loader: TLoader = "init-loader";
  data: Record<string, TWorkspacePage> = {};
  collections: Record<string, TWikiCollection> = {};
  collectionsLoaded = false;
  error: { title: string; description: string } | undefined = undefined;
  filters: TPageFilters = { searchQuery: "", sortKey: "updated_at", sortBy: "desc" };
  service = new WikiService();

  constructor(private store: CoreRootStore) {
    makeObservable(this, {
      loader: observable.ref,
      data: observable,
      collections: observable,
      collectionsLoaded: observable.ref,
      error: observable,
      filters: observable,
      isAnyPageAvailable: computed,
      canCurrentUserCreatePage: computed,
      isCurrentUserWorkspaceMember: computed,
      sortedCollections: computed,
      defaultCollection: computed,
      updateFilters: action,
      clearAllFilters: action,
      fetchPagesList: action,
      fetchPageDetails: action,
      createPage: action,
      removePage: action,
      fetchCollections: action,
      createCollection: action,
      updateCollection: action,
      deleteCollection: action,
      addPageToStore: action,
      moveWikiPage: action,
    });
  }

  private get workspaceRole() {
    const { workspaceSlug } = this.store.router;
    if (!workspaceSlug) return undefined;
    return this.store.user.permission.getWorkspaceRoleByWorkspaceSlug(workspaceSlug) as EUserPermissions | undefined;
  }

  get isCurrentUserWorkspaceMember() {
    return (this.workspaceRole ?? 0) >= EUserPermissions.MEMBER;
  }

  get isAnyPageAvailable() {
    if (this.loader) return true;
    return Object.keys(this.data).length > 0;
  }

  get canCurrentUserCreatePage() {
    return this.isCurrentUserWorkspaceMember || this.sortedCollections.some((c) => (c.current_user_access ?? -1) >= 2);
  }

  get sortedCollections() {
    return Object.values(this.collections).toSorted((a, b) => {
      if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
      return a.sort_order - b.sort_order;
    });
  }

  get defaultCollection() {
    return Object.values(this.collections).find((c) => c.is_default);
  }

  getCollectionById = computedFn((collectionId: string) => this.collections[collectionId]);

  getPageById = computedFn((pageId: string) => this.data?.[pageId] || undefined);

  private byOrder = (ids: string[]) =>
    ids.toSorted((a, b) => {
      const pa = this.data[a];
      const pb = this.data[b];
      return (
        (pa?.sort_order ?? 0) - (pb?.sort_order ?? 0) || String(pa?.created_at).localeCompare(String(pb?.created_at))
      );
    });

  getRootPageIds = computedFn((collectionId: string, archived = false) =>
    this.byOrder(
      Object.values(this.data)
        .filter(
          (p) => p.collection_id === collectionId && !p.parent_id && !!p.archived_at === archived && !p.deleted_at
        )
        .map((p) => p.id as string)
    )
  );

  getChildPageIds = computedFn((pageId: string, archived = false) =>
    this.byOrder(
      Object.values(this.data)
        .filter((p) => p.parent_id === pageId && !!p.archived_at === archived && !p.deleted_at)
        .map((p) => p.id as string)
    )
  );

  getAncestorIds = computedFn((pageId: string) => {
    const ancestors: string[] = [];
    let current = this.data[pageId];
    const seen = new Set<string>();
    while (current?.parent_id && !seen.has(current.parent_id)) {
      seen.add(current.parent_id);
      ancestors.unshift(current.parent_id);
      current = this.data[current.parent_id];
    }
    return ancestors;
  });

  getArchivedPageIds = computedFn(() =>
    Object.values(this.data)
      .filter((p) => !!p.archived_at && !p.deleted_at && !(p.parent_id && this.data[p.parent_id]?.archived_at))
      .map((p) => p.id as string)
  );

  // project-store compatible helpers, scoped to the wiki
  getCurrentProjectPageIdsByTab = computedFn((pageType: TPageNavigationTabs) =>
    filterPagesByPageType(pageType, Object.values(this.data)).map((p) => p.id as string)
  );

  getCurrentProjectPageIds = computedFn((_projectId: string) => Object.keys(this.data));

  getCurrentProjectFilteredPageIdsByTab = computedFn((pageType: TPageNavigationTabs) => {
    const pages = filterPagesByPageType(pageType, Object.values(this.data)).filter(
      (p) =>
        getPageName(p.name).toLowerCase().includes(this.filters.searchQuery.toLowerCase()) &&
        shouldFilterPage(p, this.filters.filters)
    );
    return orderPages(pages, this.filters.sortKey, this.filters.sortBy).map((p) => p.id as string);
  });

  updateFilters = <T extends keyof TPageFilters>(filterKey: T, filterValue: TPageFilters[T]) => {
    runInAction(() => set(this.filters, [filterKey], filterValue));
  };

  clearAllFilters = () => runInAction(() => set(this.filters, ["filters"], {}));

  addPageToStore = (page: TWikiPage) => {
    if (!page?.id) return undefined;
    const existing = this.data[page.id];
    if (existing) {
      existing.mutateProperties(page, false);
      existing.mutateWikiProperties(page);
      return existing;
    }
    const instance = new WorkspacePage(this.store, page);
    set(this.data, [page.id], instance);
    return instance;
  };

  fetchCollections = async (workspaceSlug: string) => {
    const collections = await this.service.fetchCollections(workspaceSlug);
    runInAction(() => {
      this.collections = Object.fromEntries(collections.map((c) => [c.id, c]));
      this.collectionsLoaded = true;
    });
    return collections;
  };

  createCollection = async (workspaceSlug: string, data: Partial<TWikiCollection>) => {
    const collection = await this.service.createCollection(workspaceSlug, data);
    runInAction(() => set(this.collections, [collection.id], collection));
    return collection;
  };

  updateCollection = async (workspaceSlug: string, collectionId: string, data: Partial<TWikiCollection>) => {
    const collection = await this.service.updateCollection(workspaceSlug, collectionId, data);
    runInAction(() => set(this.collections, [collection.id], collection));
    return collection;
  };

  deleteCollection = async (workspaceSlug: string, collectionId: string, archivePages: boolean) => {
    await this.service.deleteCollection(workspaceSlug, collectionId, archivePages);
    runInAction(() => unset(this.collections, [collectionId]));
    // Pages were refiled (and possibly archived or made private) on the server.
    await Promise.all([this.fetchCollections(workspaceSlug), this.fetchPagesList(workspaceSlug)]);
  };

  fetchPagesList = async (workspaceSlug: string, _projectId?: string, _pageType?: TPageNavigationTabs) => {
    if (!workspaceSlug) return undefined;
    try {
      runInAction(() => {
        this.loader = Object.keys(this.data).length > 0 ? "mutation-loader" : "init-loader";
        this.error = undefined;
      });
      const pages = await this.service.fetchPages(workspaceSlug);
      runInAction(() => {
        const seen = new Set<string>();
        for (const page of pages) {
          if (!page?.id) continue;
          seen.add(page.id);
          const existing = this.data[page.id];
          if (existing) {
            // The editor owns the title of an open page; keep it.
            const { name: _name, ...rest } = page;
            existing.mutateProperties(rest, false);
            existing.mutateWikiProperties(page);
          } else {
            set(this.data, [page.id], new WorkspacePage(this.store, page));
          }
        }
        // Drop pages that are no longer visible (deleted, moved to a private collection, ...).
        for (const id of Object.keys(this.data)) if (!seen.has(id)) unset(this.data, [id]);
        this.loader = undefined;
      });
      return pages;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = { title: "Failed", description: "Failed to fetch the wiki pages, please try again later." };
      });
      throw error;
    }
  };

  fetchPageDetails = async (
    workspaceSlug: string,
    pageIdOrProjectId: string,
    maybePageId?: string,
    options?: { trackVisit?: boolean }
  ) => {
    // Accepts (slug, pageId) for the wiki and (slug, projectId, pageId) for callers written against projects.
    const pageId = maybePageId ?? pageIdOrProjectId;
    if (!workspaceSlug || !pageId) return undefined;
    try {
      const page = await this.service.fetchPage(workspaceSlug, pageId, options?.trackVisit ?? true);
      runInAction(() => {
        this.addPageToStore(page);
        this.loader = undefined;
      });
      return page;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = { title: "Failed", description: "Failed to fetch the page, please try again later." };
      });
      throw error;
    }
  };

  createWikiPage = async (
    workspaceSlug: string,
    data: Partial<TPage> & { parent_id?: string | null; collection_id?: string | null }
  ) => {
    const page = await this.service.createPage(workspaceSlug, data);
    let instance: TWorkspacePage | undefined;
    runInAction(() => {
      instance = this.addPageToStore(page);
      const parent = data.parent_id ? this.data[data.parent_id] : undefined;
      if (parent) parent.mutateWikiProperties({ sub_pages_count: parent.sub_pages_count + 1 });
    });
    return instance;
  };

  /** What shared components call: files the page under the current page's parent context, or the default collection. */
  createPage = async (pageData: Partial<TPage> & { parent_id?: string | null; collection_id?: string | null }) => {
    const { workspaceSlug } = this.store.router;
    if (!workspaceSlug) return undefined;
    const instance = await this.createWikiPage(workspaceSlug, pageData);
    return instance ? (instance as unknown as TPage) : undefined;
  };

  removePage = async ({ pageId, shouldSync = true }: { pageId: string; shouldSync?: boolean }) => {
    const { workspaceSlug } = this.store.router;
    if (!workspaceSlug || !pageId) return;
    if (shouldSync) await this.service.removePage(workspaceSlug, pageId);
    runInAction(() => {
      // Children were detached to the top level on the server.
      for (const page of Object.values(this.data)) {
        if (page.parent_id === pageId) page.mutateWikiProperties({ parent_id: null });
      }
      unset(this.data, [pageId]);
    });
  };

  movePage = async () => {
    throw new Error("Wiki pages move within the wiki; use moveWikiPage.");
  };

  moveWikiPage = async (workspaceSlug: string, pageId: string, payload: TWikiPageMovePayload) => {
    const page = this.data[pageId];
    if (!page) return;
    const before = {
      parent_id: page.parent_id,
      collection_id: page.collection_id,
      sort_order: page.sort_order,
    };
    // Optimistic: the tree reflows at once; the subtree follows its root's collection.
    runInAction(() => {
      const next: Partial<TWikiPage> = {};
      if (payload.parent_id !== undefined) next.parent_id = payload.parent_id;
      if (payload.collection_id !== undefined) next.collection_id = payload.collection_id;
      if (payload.parent_id) next.collection_id = this.data[payload.parent_id]?.collection_id ?? page.collection_id;
      if (payload.sort_order !== undefined) next.sort_order = payload.sort_order;
      page.mutateWikiProperties(next);
      if (next.collection_id) this.refileSubtree(pageId, next.collection_id);
    });
    try {
      const updated = await this.service.movePage(workspaceSlug, pageId, payload);
      runInAction(() => this.addPageToStore(updated));
    } catch (error) {
      runInAction(() => {
        page.mutateWikiProperties(before);
        if (before.collection_id) this.refileSubtree(pageId, before.collection_id);
      });
      throw error;
    }
  };

  private refileSubtree(pageId: string, collectionId: string) {
    for (const childId of this.getChildPageIds(pageId)) {
      this.data[childId]?.mutateWikiProperties({ collection_id: collectionId });
      this.refileSubtree(childId, collectionId);
    }
  }

  /** A sort order that places an item between two neighbours (either may be missing). */
  static between(before?: number, after?: number) {
    if (before === undefined && after === undefined) return SORT_STEP;
    if (before === undefined) return (after as number) - SORT_STEP;
    if (after === undefined) return before + SORT_STEP;
    return (before + after) / 2;
  }
}
