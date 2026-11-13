/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ConnectionConfiguration } from "@hocuspocus/server";
import { logger } from "@plane/logger";
import { AppError } from "@/lib/errors";
import { WorkspacePageService } from "@/services/page/workspace-page.service";
import type { HocusPocusServerContext } from "@/types";

const EDIT = 2;

/**
 * Apply the wiki's access policy to one websocket connection.
 *
 * Project pages only check access when a document is first loaded. Wiki
 * collections have view-only members, and a document already loaded for an
 * editor would otherwise accept anyone who knows its id, so every connection
 * is checked: no access refuses it, anything below edit makes it read-only.
 */
export const enforceWikiPageAccess = async ({
  context,
  documentName,
  connection,
}: {
  context: HocusPocusServerContext;
  documentName: string;
  connection: ConnectionConfiguration;
}) => {
  const service = new WorkspacePageService({ workspaceSlug: context.workspaceSlug, cookie: context.cookie });
  let page;
  try {
    page = await service.fetchAccess(documentName);
  } catch (error) {
    logger.warn("Wiki page access refused", { documentName });
    throw new AppError(error, { code: "AUTH_PAGE_ACCESS_DENIED" });
  }
  const level = page?.current_user_access ?? -1;
  if (level < EDIT || page?.is_locked || page?.archived_at) connection.readOnly = true;
};
