/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { action, computed, makeObservable, observable, runInAction } from "mobx";
import { computedFn } from "mobx-utils";
// plane imports
import { EPageAccess, EUserPermissions } from "@plane/constants";
// store
import { BasePage } from "@/store/pages/base-page";
import type { TPageInstance } from "@/store/pages/base-page";
import type { RootStore } from "@/store/root.store";
// plane web
import { WikiService } from "@/plane-web/services/wiki.service";
import type { TWikiAccessLevel, TWikiPage } from "@/plane-web/types/wiki";
import { WIKI_ACCESS } from "@/plane-web/types/wiki";

const wikiService = new WikiService();

export type TWorkspacePage = TPageInstance & {
  parent_id: string | null;
  collection_id: string | null;
  page_collection_id: string | null;
  sort_order: number;
  sub_pages_count: number;
  current_user_access: TWikiAccessLevel | undefined;
  mutateWikiProperties: (page: Partial<TWikiPage>) => void;
};

/**
 * A workspace wiki page. Editing, versions and live collaboration come from
 * BasePage unchanged; what differs is where the API lives and who may do what,
 * which follows the collection the page is filed in rather than a project role.
 */
export class WorkspacePage extends BasePage implements TWorkspacePage {
  parent_id: string | null;
  collection_id: string | null;
  page_collection_id: string | null;
  sort_order: number;
  sub_pages_count: number;
  current_user_access: TWikiAccessLevel | undefined;

  constructor(store: RootStore, page: TWikiPage) {
    const { workspaceSlug } = store.router;
    const required = () => {
      if (!workspaceSlug || !page.id) throw new Error("Missing required fields.");
      return { slug: workspaceSlug, id: page.id };
    };
    super(store, page, {
      update: async (payload) => {
        const { slug, id } = required();
        return await wikiService.updatePage(slug, id, payload);
      },
      updateDescription: async (document) => {
        const { slug, id } = required();
        await wikiService.updateDescription(slug, id, document);
      },
      updateAccess: async (payload) => {
        const { slug, id } = required();
        await wikiService.updatePage(slug, id, payload);
      },
      lock: async () => {
        const { slug, id } = required();
        await wikiService.lockPage(slug, id);
      },
      unlock: async () => {
        const { slug, id } = required();
        await wikiService.unlockPage(slug, id);
      },
      archive: async () => {
        const { slug, id } = required();
        return await wikiService.archivePage(slug, id);
      },
      restore: async () => {
        const { slug, id } = required();
        await wikiService.restorePage(slug, id);
      },
      duplicate: async () => {
        const { slug, id } = required();
        const copy = await wikiService.duplicatePage(slug, id);
        // The copy belongs in the tree right away, next to its source.
        store.workspacePages.addPageToStore(copy);
        return copy;
      },
    });
    this.parent_id = page.parent_id ?? page.parent ?? null;
    this.collection_id = page.collection_id ?? null;
    this.page_collection_id = page.page_collection_id ?? null;
    this.sort_order = page.sort_order ?? 65535;
    this.sub_pages_count = page.sub_pages_count ?? 0;
    this.current_user_access = page.current_user_access;
    makeObservable(this, {
      parent_id: observable.ref,
      collection_id: observable.ref,
      page_collection_id: observable.ref,
      sort_order: observable.ref,
      sub_pages_count: observable.ref,
      current_user_access: observable.ref,
      mutateWikiProperties: action,
      canCurrentUserAccessPage: computed,
      canCurrentUserEditPage: computed,
      canCurrentUserDuplicatePage: computed,
      canCurrentUserLockPage: computed,
      canCurrentUserChangeAccess: computed,
      canCurrentUserArchivePage: computed,
      canCurrentUserDeletePage: computed,
      canCurrentUserFavoritePage: computed,
      canCurrentUserMovePage: computed,
      isContentEditable: computed,
    });
  }

  mutateWikiProperties = (page: Partial<TWikiPage>) => {
    runInAction(() => {
      if (page.parent_id !== undefined) this.parent_id = page.parent_id;
      else if (page.parent !== undefined) this.parent_id = page.parent;
      if (page.collection_id !== undefined) this.collection_id = page.collection_id;
      if (page.page_collection_id !== undefined) this.page_collection_id = page.page_collection_id;
      if (page.sort_order !== undefined) this.sort_order = page.sort_order;
      if (page.sub_pages_count !== undefined) this.sub_pages_count = page.sub_pages_count;
      if (page.current_user_access !== undefined) this.current_user_access = page.current_user_access;
    });
  };

  private get workspaceRole(): EUserPermissions | undefined {
    const { workspaceSlug } = this.rootStore.router;
    if (!workspaceSlug) return undefined;
    return this.rootStore.user.permission.getWorkspaceRoleByWorkspaceSlug(workspaceSlug) as
      | EUserPermissions
      | undefined;
  }

  /** The collection level the server granted, or what the role implies when it is not known yet. */
  private accessLevel = computedFn((): number => {
    const collection = this.collection_id
      ? this.rootStore.workspacePages.getCollectionById(this.collection_id)
      : undefined;
    const level = collection?.current_user_access ?? this.current_user_access;
    if (level !== undefined && level !== null) return level;
    return (this.workspaceRole ?? 0) >= EUserPermissions.MEMBER ? WIKI_ACCESS.EDIT : -1;
  });

  private get isAdmin() {
    return this.workspaceRole === EUserPermissions.ADMIN;
  }

  get canCurrentUserAccessPage() {
    return this.access === EPageAccess.PUBLIC || this.isCurrentUserOwner;
  }

  get canCurrentUserEditPage() {
    if (this.access !== EPageAccess.PUBLIC) return this.isCurrentUserOwner;
    return this.isCurrentUserOwner || this.accessLevel() >= WIKI_ACCESS.EDIT;
  }

  get canCurrentUserDuplicatePage() {
    return this.accessLevel() >= WIKI_ACCESS.EDIT;
  }

  get canCurrentUserLockPage() {
    return this.isCurrentUserOwner || this.isAdmin;
  }

  get canCurrentUserChangeAccess() {
    return this.isCurrentUserOwner;
  }

  get canCurrentUserArchivePage() {
    return this.canCurrentUserEditPage;
  }

  get canCurrentUserDeletePage() {
    return this.isCurrentUserOwner || this.isAdmin;
  }

  get canCurrentUserFavoritePage() {
    // Favorites are tied to projects upstream; wiki pages are reached from the tree.
    return false;
  }

  get canCurrentUserMovePage() {
    return this.canCurrentUserEditPage;
  }

  get isContentEditable() {
    return !this.archived_at && !this.is_locked && this.canCurrentUserEditPage;
  }

  getRedirectionLink = computedFn(() => {
    const { workspaceSlug } = this.rootStore.router;
    return `/${workspaceSlug}/wiki/${this.id}`;
  });
}
