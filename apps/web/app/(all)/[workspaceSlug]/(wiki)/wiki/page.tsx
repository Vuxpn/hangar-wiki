/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// components
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PageHead } from "@/components/core/page-title";
// plane web
import { WikiHome, WikiHomeHeader } from "@/plane-web/components/wiki/home";
import type { Route } from "./+types/page";

function WikiHomePage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Wiki" />
      <AppHeader header={<WikiHomeHeader />} />
      <ContentWrapper>
        <WikiHome workspaceSlug={params.workspaceSlug} />
      </ContentWrapper>
    </>
  );
}

export default observer(WikiHomePage);
