/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Outlet } from "react-router";
import useSWR from "swr";
// plane imports
import { SIDEBAR_WIDTH } from "@plane/constants";
import { useLocalStorage } from "@plane/hooks";
// components
import { ResizableSidebar } from "@/components/sidebar/resizable-sidebar";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useAppTheme } from "@/hooks/store/use-app-theme";
// plane web
import { WikiSidebar } from "@/plane-web/components/wiki/sidebar/root";
import type { Route } from "./+types/layout";

/** The workspace wiki: a collection tree on the left, the page on the right. */
function WikiLayout({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { sidebarCollapsed, toggleSidebar, sidebarPeek, toggleSidebarPeek, isAnySidebarDropdownOpen } = useAppTheme();
  const { storedValue, setValue } = useLocalStorage("sidebarWidth", SIDEBAR_WIDTH);
  const [sidebarWidth, setSidebarWidth] = useState<number>(storedValue ?? SIDEBAR_WIDTH);
  const { fetchCollections, fetchPagesList } = usePageStore(EPageStoreType.WORKSPACE);

  useSWR(`WIKI_COLLECTIONS_${workspaceSlug}`, () => fetchCollections(workspaceSlug), { revalidateOnFocus: true });
  useSWR(`WIKI_PAGES_${workspaceSlug}`, () => fetchPagesList(workspaceSlug), { revalidateOnFocus: true });

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-lg border border-subtle">
      <div id="full-screen-portal" className="absolute inset-0 w-full" />
      <div className="relative flex size-full overflow-hidden">
        <ResizableSidebar
          showPeek={sidebarPeek}
          defaultWidth={storedValue ?? 250}
          width={sidebarWidth}
          setWidth={setSidebarWidth}
          defaultCollapsed={sidebarCollapsed}
          peekDuration={1500}
          onWidthChange={(width) => setValue(width)}
          onCollapsedChange={toggleSidebar}
          isCollapsed={sidebarCollapsed}
          toggleCollapsed={toggleSidebar}
          togglePeek={toggleSidebarPeek}
          isAnySidebarDropdownOpen={isAnySidebarDropdownOpen}
        >
          <WikiSidebar />
        </ResizableSidebar>
        <main className="relative flex h-full w-full flex-col overflow-hidden bg-surface-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default observer(WikiLayout);
