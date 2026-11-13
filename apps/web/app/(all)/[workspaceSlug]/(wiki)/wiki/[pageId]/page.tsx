/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { getButtonStyling } from "@plane/propel/button";
import type { TSearchEntityRequestPayload, TWebhookConnectionQueryParams } from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { cn } from "@plane/utils";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PageHead } from "@/components/core/page-title";
import type { TPageRootConfig, TPageRootHandlers } from "@/components/pages/editor/page-root";
import { PageRoot } from "@/components/pages/editor/page-root";
// hooks
import { useEditorConfig } from "@/hooks/editor";
import { EPageStoreType, usePage, usePageStore } from "@/hooks/store";
import { useEditorAsset } from "@/hooks/store/use-editor-asset";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useAppRouter } from "@/hooks/use-app-router";
// services
import { WorkspaceService } from "@/services/workspace.service";
// plane web
import { WikiPageHeader } from "@/plane-web/components/wiki/header";
import { WikiService } from "@/plane-web/services/wiki.service";
import type { Route } from "./+types/page";

const workspaceService = new WorkspaceService();
const wikiService = new WikiService();

const storeType = EPageStoreType.WORKSPACE;

function WikiPageDetailsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, pageId } = params;
  const router = useAppRouter();
  const { t } = useTranslation();
  // store hooks
  const { createPage, fetchPageDetails } = usePageStore(storeType);
  const page = usePage({ pageId, storeType });
  const { getWorkspaceBySlug } = useWorkspace();
  const { uploadEditorAsset, duplicateEditorAsset } = useEditorAsset();
  const { getEditorFileHandlers } = useEditorConfig();
  // derived values
  const workspaceId = workspaceSlug ? (getWorkspaceBySlug(workspaceSlug)?.id ?? "") : "";
  const { canCurrentUserAccessPage, id, name, updateDescription } = page ?? {};

  const fetchEntityCallback = useCallback(
    async (payload: TSearchEntityRequestPayload) => await workspaceService.searchEntity(workspaceSlug, payload),
    [workspaceSlug]
  );

  const { error: pageDetailsError } = useSWR(
    `WIKI_PAGE_DETAILS_${pageId}`,
    () => fetchPageDetails(workspaceSlug, pageId),
    { revalidateIfStale: true, revalidateOnFocus: true, revalidateOnReconnect: true }
  );

  const pageRootHandlers: TPageRootHandlers = useMemo(
    () => ({
      create: createPage,
      fetchAllVersions: async (versionPageId) => await wikiService.fetchVersions(workspaceSlug, versionPageId),
      fetchDescriptionBinary: async () => {
        if (!id) return new ArrayBuffer(0);
        return await wikiService.fetchDescriptionBinary(workspaceSlug, id);
      },
      fetchEntity: fetchEntityCallback,
      fetchVersionDetails: async (versionPageId, versionId) =>
        await wikiService.fetchVersion(workspaceSlug, versionPageId, versionId),
      // Restoring writes the version's content through the editor; nothing to call here.
      restoreVersion: async () => {},
      getRedirectionLink: (targetPageId) =>
        targetPageId ? `/${workspaceSlug}/wiki/${targetPageId}` : `/${workspaceSlug}/wiki`,
      updateDescription: updateDescription ?? (async () => {}),
    }),
    [createPage, fetchEntityCallback, id, updateDescription, workspaceSlug]
  );

  const pageRootConfig: TPageRootConfig = useMemo(
    () => ({
      fileHandler: getEditorFileHandlers({
        uploadFile: async (blockId, file) => {
          const { asset_id } = await uploadEditorAsset({
            blockId,
            data: { entity_identifier: id ?? "", entity_type: EFileAssetType.PAGE_DESCRIPTION },
            file,
            workspaceSlug,
          });
          return asset_id;
        },
        duplicateFile: async (assetId: string) => {
          const { asset_id } = await duplicateEditorAsset({
            assetId,
            entityId: id,
            entityType: EFileAssetType.PAGE_DESCRIPTION,
            workspaceSlug,
          });
          return asset_id;
        },
        workspaceId,
        workspaceSlug,
      }),
    }),
    [getEditorFileHandlers, workspaceId, workspaceSlug, uploadEditorAsset, id, duplicateEditorAsset]
  );

  const webhookConnectionParams: TWebhookConnectionQueryParams = useMemo(
    () => ({ documentType: "workspace_page", workspaceSlug }),
    [workspaceSlug]
  );

  useEffect(() => {
    if (page?.deleted_at && page?.id) router.push(pageRootHandlers.getRedirectionLink());
  }, [page?.deleted_at, page?.id, router, pageRootHandlers]);

  let content: React.ReactNode;
  if ((!page || !id) && !pageDetailsError) {
    content = (
      <div className="grid size-full place-items-center">
        <LogoSpinner />
      </div>
    );
  } else if (pageDetailsError || !canCurrentUserAccessPage || !page) {
    content = (
      <div className="flex h-full w-full flex-col items-center justify-center">
        <h3 className="text-center text-16 font-semibold">{t("workspace_wiki.not_found.title")}</h3>
        <p className="mt-3 text-center text-13 text-secondary">{t("workspace_wiki.not_found.description")}</p>
        <Link href={`/${workspaceSlug}/wiki`} className={cn(getButtonStyling("secondary", "base"), "mt-5")}>
          {t("workspace_wiki.not_found.back")}
        </Link>
      </div>
    );
  } else {
    content = (
      <div className="flex h-full flex-col justify-between">
        <div className="relative flex h-full w-full flex-shrink-0 flex-col overflow-hidden">
          <PageRoot
            config={pageRootConfig}
            handlers={pageRootHandlers}
            storeType={storeType}
            page={page}
            webhookConnectionParams={webhookConnectionParams}
            workspaceSlug={workspaceSlug}
          />
        </div>
      </div>
    );
  }

  return (
    <>
      <PageHead title={name || "Wiki"} />
      <AppHeader header={<WikiPageHeader />} />
      <ContentWrapper>{content}</ContentWrapper>
    </>
  );
}

export default observer(WikiPageDetailsPage);
