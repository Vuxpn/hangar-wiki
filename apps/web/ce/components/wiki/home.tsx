/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { BookOpen, Globe2, Lock } from "lucide-react";
import { orderBy } from "lodash-es";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { PageIcon } from "@plane/propel/icons";
import { Breadcrumbs, Header } from "@plane/ui";
import { calculateTimeAgo, getPageName } from "@plane/utils";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useMember } from "@/hooks/store/use-member";

const storeType = EPageStoreType.WORKSPACE;

export function WikiHomeHeader() {
  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={<BreadcrumbLink label="Wiki" icon={<BookOpen className="h-4 w-4 text-tertiary" />} isLast />}
          />
        </Breadcrumbs>
      </Header.LeftItem>
    </Header>
  );
}

/** Landing view: the collections, and what changed most recently. */
export const WikiHome = observer(function WikiHome({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const store = usePageStore(storeType);
  const { getUserDetails } = useMember();

  const pages = Object.values(store.data).filter((page) => !page.archived_at);
  const recent = orderBy(pages, [(page) => String(page.updated_at ?? "")], ["desc"]).slice(0, 12);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-8">
      <section className="flex flex-col gap-3">
        <h2 className="text-16 font-semibold text-primary">{t("workspace_wiki.home.collections")}</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {store.sortedCollections.map((collection) => {
            const count = pages.filter((page) => page.collection_id === collection.id).length;
            return (
              <div key={collection.id} className="flex flex-col gap-1 rounded-lg border border-subtle bg-layer-1 p-4">
                <div className="flex items-center gap-2 text-14 font-medium text-primary">
                  {collection.access === 1 ? <Lock className="size-3.5" /> : <Globe2 className="size-3.5" />}
                  <span className="truncate">
                    {collection.is_default ? t("wiki_collections.predefined.general") : collection.name}
                  </span>
                </div>
                <span className="text-12 text-tertiary">{t("workspace_wiki.home.page_count", { count })}</span>
              </div>
            );
          })}
        </div>
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-16 font-semibold text-primary">{t("workspace_wiki.home.recent")}</h2>
        {recent.length === 0 ? (
          <div className="rounded-lg border border-dashed border-subtle p-6 text-center text-13 text-tertiary">
            {t("workspace_wiki.home.empty")}
          </div>
        ) : (
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {recent.map((page) => {
              const author = page.updated_by ? getUserDetails(page.updated_by) : undefined;
              return (
                <Link
                  key={page.id}
                  href={`/${workspaceSlug}/wiki/${page.id}`}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-layer-transparent-hover"
                >
                  <span className="grid size-4 flex-shrink-0 place-items-center">
                    {page.logo_props?.in_use ? (
                      <Logo logo={page.logo_props} size={14} type="lucide" />
                    ) : (
                      <PageIcon className="size-3.5 text-tertiary" />
                    )}
                  </span>
                  <span className="min-w-0 flex-grow truncate text-13 text-primary">{getPageName(page.name)}</span>
                  <span className="flex-shrink-0 text-12 text-tertiary">
                    {author?.display_name ? `${author.display_name} · ` : ""}
                    {page.updated_at ? calculateTimeAgo(page.updated_at) : ""}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
});
