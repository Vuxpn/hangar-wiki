/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { IconButton } from "@plane/propel/icon-button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { CustomSelect, EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
// components
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
// hooks
import { useMember } from "@/hooks/store/use-member";
// plane web
import { WikiService } from "@/plane-web/services/wiki.service";
import type { TWikiCollection } from "@/plane-web/types/wiki";

const wikiService = new WikiService();

type Props = {
  isOpen: boolean;
  onClose: () => void;
  collection: TWikiCollection;
  canManage: boolean;
};

export const CollectionMembersModal = observer(function CollectionMembersModal(props: Props) {
  const { isOpen, onClose, collection, canManage } = props;
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  const { getUserDetails } = useMember();
  const slug = workspaceSlug?.toString() ?? "";
  const [newMember, setNewMember] = useState<string | null>(null);
  const [newAccess, setNewAccess] = useState(2);
  const { data: members, mutate } = useSWR(isOpen ? `WIKI_COLLECTION_MEMBERS_${collection.id}` : null, () =>
    wikiService.fetchCollectionMembers(slug, collection.id)
  );

  const levels = [
    { value: 0, label: t("workspace_wiki.members.view") },
    { value: 1, label: t("workspace_wiki.members.comment") },
    { value: 2, label: t("workspace_wiki.members.edit") },
  ];
  const levelLabel = (value: number) => levels.find((level) => level.value === value)?.label;

  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await mutate();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("workspace_wiki.toasts.members_error") });
    }
  };

  const existing = new Set((members ?? []).map((member) => member.member));

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.TOP} width={EModalWidth.XL}>
      <div className="space-y-4 p-5">
        <div>
          <h3 className="text-18 font-medium text-primary">{t("common.members")}</h3>
          <p className="text-12 text-tertiary">
            {collection.access === 1
              ? t("workspace_wiki.members.private_hint")
              : t("workspace_wiki.members.public_hint")}
          </p>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <div className="grow">
              <MemberDropdown
                value={newMember}
                onChange={setNewMember}
                multiple={false}
                buttonVariant="border-with-text"
                buttonContainerClassName="w-full"
                buttonClassName="w-full"
                placeholder={t("workspace_wiki.members.pick")}
              />
            </div>
            <CustomSelect
              value={newAccess}
              label={levelLabel(newAccess)}
              onChange={(value: number) => setNewAccess(value)}
            >
              {levels.map((level) => (
                <CustomSelect.Option key={level.value} value={level.value}>
                  {level.label}
                </CustomSelect.Option>
              ))}
            </CustomSelect>
            <Button
              variant="primary"
              size="sm"
              disabled={!newMember || existing.has(newMember)}
              onClick={() =>
                newMember &&
                run(async () => {
                  await wikiService.addCollectionMember(slug, collection.id, { member: newMember, access: newAccess });
                  setNewMember(null);
                })
              }
            >
              {t("common.add")}
            </Button>
          </div>
        )}
        <div className="divide-y divide-subtle rounded-md border border-subtle">
          {(members ?? []).length === 0 && (
            <p className="px-3 py-2 text-13 text-tertiary">{t("workspace_wiki.members.empty")}</p>
          )}
          {(members ?? []).map((member) => {
            const user = getUserDetails(member.member);
            return (
              <div key={member.id} className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="truncate text-13 text-primary">{user?.display_name ?? member.member}</span>
                <div className="flex items-center gap-1">
                  {canManage ? (
                    <CustomSelect
                      value={member.access}
                      label={levelLabel(member.access)}
                      onChange={(value: number) =>
                        run(() => wikiService.updateCollectionMember(slug, collection.id, member.id, value))
                      }
                    >
                      {levels.map((level) => (
                        <CustomSelect.Option key={level.value} value={level.value}>
                          {level.label}
                        </CustomSelect.Option>
                      ))}
                    </CustomSelect>
                  ) : (
                    <span className="text-12 text-tertiary">{levelLabel(member.access)}</span>
                  )}
                  {canManage && (
                    <IconButton
                      variant="ghost"
                      size="sm"
                      icon={Trash2}
                      aria-label={t("common.remove")}
                      onClick={() => run(() => wikiService.removeCollectionMember(slug, collection.id, member.id))}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex justify-end">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t("close")}
          </Button>
        </div>
      </div>
    </ModalCore>
  );
});
