/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { BookOpen } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { PageIcon } from "@plane/propel/icons";
import { Breadcrumbs, Header } from "@plane/ui";
import { getPageName } from "@plane/utils";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SwitcherIcon } from "@/components/common/switcher-label";
import { PageHeaderActions } from "@/components/pages/header/actions";
import { PageSyncingBadge } from "@/components/pages/header/syncing-badge";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";

const storeType = EPageStoreType.WORKSPACE;

/** Wiki › collection › ancestors › page, with the page actions on the right. */
export const WikiPageHeader = observer(function WikiPageHeader() {
  const { workspaceSlug, pageId } = useParams();
  const { t } = useTranslation();
  const store = usePageStore(storeType);
  // Read through the wiki store: the generic page hook types the page without its filing.
  const page = store.getPageById(pageId?.toString() ?? "");
  const slug = workspaceSlug?.toString() ?? "";

  if (!page) return null;

  const collection = page.collection_id ? store.getCollectionById(page.collection_id) : undefined;
  const ancestors = store
    .getAncestorIds(page.id ?? "")
    .map((id) => store.getPageById(id))
    .filter(Boolean);

  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs isLoading={store.loader === "init-loader"}>
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label="Wiki"
                href={`/${slug}/wiki`}
                icon={<BookOpen className="h-4 w-4 text-tertiary" />}
              />
            }
          />
          {collection && (
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label={collection.is_default ? t("wiki_collections.predefined.general") : collection.name}
                  href={`/${slug}/wiki`}
                />
              }
            />
          )}
          {ancestors.map((ancestor) => (
            <Breadcrumbs.Item
              key={ancestor?.id}
              component={<BreadcrumbLink label={getPageName(ancestor?.name)} href={`/${slug}/wiki/${ancestor?.id}`} />}
            />
          ))}
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label={getPageName(page.name)}
                icon={<SwitcherIcon logo_props={page.logo_props} LabelIcon={PageIcon} size={16} />}
                isLast
              />
            }
          />
        </Breadcrumbs>
      </Header.LeftItem>
      <Header.RightItem>
        <PageSyncingBadge syncStatus={page.isSyncingWithServer} />
        <PageHeaderActions page={page} storeType={storeType} />
      </Header.RightItem>
    </Header>
  );
});
