/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.API_BASE_URL = "http://api.test";
  process.env.LIVE_SERVER_SECRET_KEY = "unit-test-live-secret";
});

// A plain function rather than a spy: the refusal case must reject without a spy recording it.
const api = vi.hoisted(() => ({ fetchAccess: async (_pageId: string): Promise<unknown> => ({}) }));
vi.mock("@/services/page/workspace-page.service", () => ({
  WorkspacePageService: class {
    fetchAccess = (pageId: string) => api.fetchAccess(pageId);
  },
}));

import { enforceWikiPageAccess } from "@/lib/wiki-access";

const context = { workspaceSlug: "ws", cookie: "session=1" } as never;
const connect = () => ({ readOnly: false, requiresAuthentication: true, isAuthenticated: true });

describe("enforceWikiPageAccess", () => {
  it("leaves editors writable", async () => {
    api.fetchAccess = async () => ({ current_user_access: 2, is_locked: false, archived_at: null });
    const connection = connect();
    await enforceWikiPageAccess({ context, documentName: "p", connection });
    expect(connection.readOnly).toBe(false);
  });

  it.each([
    [{ current_user_access: 0 }],
    [{ current_user_access: 1 }],
    [{ current_user_access: 2, is_locked: true }],
    [{ current_user_access: 2, archived_at: "2026-11-13" }],
  ])("makes %o read-only", async (page) => {
    api.fetchAccess = async () => page;
    const connection = connect();
    await enforceWikiPageAccess({ context, documentName: "p", connection });
    expect(connection.readOnly).toBe(true);
  });

  it("refuses a connection to a page the user cannot see", async () => {
    api.fetchAccess = async () => {
      throw new Error("Not found");
    };
    let refused: unknown;
    try {
      await enforceWikiPageAccess({ context, documentName: "p", connection: connect() });
    } catch (error) {
      refused = error;
    }
    expect(refused).toBeDefined();
  });
});
