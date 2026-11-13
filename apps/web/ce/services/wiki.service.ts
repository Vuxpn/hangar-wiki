/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TDocumentPayload, TPage, TPageVersion } from "@plane/types";
import { APIService } from "@/services/api.service";
import type { TWikiCollection, TWikiCollectionMember, TWikiPage, TWikiPageMovePayload } from "@/plane-web/types/wiki";

/** The workspace wiki routes: /api/workspaces/<slug>/wiki/... */
export class WikiService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private wikiUrl(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/wiki`;
  }

  private async send<T>(promise: Promise<{ data: T }>): Promise<T> {
    return promise
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  // collections
  fetchCollections(workspaceSlug: string): Promise<TWikiCollection[]> {
    return this.send(this.get(`${this.wikiUrl(workspaceSlug)}/collections/`));
  }

  createCollection(workspaceSlug: string, data: Partial<TWikiCollection>): Promise<TWikiCollection> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/collections/`, data));
  }

  updateCollection(
    workspaceSlug: string,
    collectionId: string,
    data: Partial<TWikiCollection>
  ): Promise<TWikiCollection> {
    return this.send(this.patch(`${this.wikiUrl(workspaceSlug)}/collections/${collectionId}/`, data));
  }

  deleteCollection(workspaceSlug: string, collectionId: string, archivePages: boolean): Promise<void> {
    return this.send(
      this.delete(`${this.wikiUrl(workspaceSlug)}/collections/${collectionId}/`, undefined, {
        params: { archive_pages: archivePages },
      })
    );
  }

  fetchCollectionMembers(workspaceSlug: string, collectionId: string): Promise<TWikiCollectionMember[]> {
    return this.send(this.get(`${this.wikiUrl(workspaceSlug)}/collections/${collectionId}/members/`));
  }

  addCollectionMember(
    workspaceSlug: string,
    collectionId: string,
    data: { member: string; access: number }
  ): Promise<TWikiCollectionMember> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/collections/${collectionId}/members/`, data));
  }

  updateCollectionMember(
    workspaceSlug: string,
    collectionId: string,
    memberId: string,
    access: number
  ): Promise<TWikiCollectionMember> {
    return this.send(
      this.patch(`${this.wikiUrl(workspaceSlug)}/collections/${collectionId}/members/${memberId}/`, { access })
    );
  }

  removeCollectionMember(workspaceSlug: string, collectionId: string, memberId: string): Promise<void> {
    return this.send(this.delete(`${this.wikiUrl(workspaceSlug)}/collections/${collectionId}/members/${memberId}/`));
  }

  // pages
  fetchPages(workspaceSlug: string): Promise<TWikiPage[]> {
    return this.send(this.get(`${this.wikiUrl(workspaceSlug)}/pages/`));
  }

  fetchPage(workspaceSlug: string, pageId: string, trackVisit: boolean): Promise<TWikiPage> {
    return this.send(
      this.get(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/`, { params: { track_visit: trackVisit } })
    );
  }

  createPage(
    workspaceSlug: string,
    data: Partial<TPage> & { parent_id?: string | null; collection_id?: string | null }
  ): Promise<TWikiPage> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/pages/`, data));
  }

  updatePage(workspaceSlug: string, pageId: string, data: Partial<TPage>): Promise<TWikiPage> {
    return this.send(this.patch(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/`, data));
  }

  removePage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.send(this.delete(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/`));
  }

  archivePage(workspaceSlug: string, pageId: string): Promise<{ archived_at: string }> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/archive/`));
  }

  restorePage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.send(this.delete(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/archive/`));
  }

  lockPage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/lock/`));
  }

  unlockPage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.send(this.delete(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/lock/`));
  }

  duplicatePage(workspaceSlug: string, pageId: string): Promise<TWikiPage> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/duplicate/`));
  }

  movePage(workspaceSlug: string, pageId: string, data: TWikiPageMovePayload): Promise<TWikiPage> {
    return this.send(this.post(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/move/`, data));
  }

  fetchDescriptionBinary(workspaceSlug: string, pageId: string): Promise<ArrayBuffer> {
    return this.send(
      this.get(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/description/`, {
        headers: { "Content-Type": "application/octet-stream" },
        responseType: "arraybuffer",
      })
    );
  }

  updateDescription(workspaceSlug: string, pageId: string, data: TDocumentPayload): Promise<void> {
    return this.send(this.patch(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/description/`, data));
  }

  // versions
  fetchVersions(workspaceSlug: string, pageId: string): Promise<TPageVersion[]> {
    return this.send(this.get(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/versions/`));
  }

  fetchVersion(workspaceSlug: string, pageId: string, versionId: string): Promise<TPageVersion> {
    return this.send(this.get(`${this.wikiUrl(workspaceSlug)}/pages/${pageId}/versions/${versionId}/`));
  }
}
