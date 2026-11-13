/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TLogoProps, TPage } from "@plane/types";

/** 0 view, 1 comment, 2 edit — the level a member has on a collection. */
export type TWikiAccessLevel = 0 | 1 | 2;

export const WIKI_ACCESS = { VIEW: 0, COMMENT: 1, EDIT: 2 } as const;

export type TWikiCollection = {
  id: string;
  name: string;
  owned_by_id: string;
  /** 0 public, 1 private; fixed once the collection exists. */
  access: 0 | 1;
  current_user_access: TWikiAccessLevel | null;
  has_pages: boolean;
  is_default: boolean;
  logo_props: TLogoProps | Record<string, never>;
  sort_order: number;
  workspace: string;
  created_at: string;
  updated_at: string;
};

export type TWikiCollectionMember = {
  id: string;
  collection: string;
  member: string;
  access: TWikiAccessLevel;
};

/** A wiki page as the wiki routes return it: a page plus where it is filed. */
export type TWikiPage = TPage & {
  parent: string | null;
  parent_id: string | null;
  collection_id: string | null;
  page_collection_id: string | null;
  sort_order: number;
  sub_pages_count?: number;
  current_user_access?: TWikiAccessLevel;
};

export type TWikiPageMovePayload = {
  parent_id?: string | null;
  collection_id?: string | null;
  sort_order?: number;
};
