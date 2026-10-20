/** Compile-only regression cases for the public boundary and host adapters. */
import type { AxiosInstance } from "axios";
import type { Ref } from "vue";
import type {
  CurrentHostContext, HostActionContext, HostAdvisorScope, HostAdvisorTransport,
  HostConfirmOptions, HostContext, HostContextualAction, HostMenuItem,
  HostPrimaryNavigationItem, HostProjectCollectionsLoader, HostUser, RegisterFn,
  ServerModule,
} from "@/extension-contract/v1";
import type { ImportModuleFn } from "@/boot/serverModules";
import type { ActionContext, ContextualAction } from "@/composables/useContextualActions";
import type { ConfirmActionOptions } from "@/composables/useConfirmAction";
import type { PrimaryNavigationItem } from "@/composables/usePrimaryNavigation";
import type { TopbarMenuItem } from "@/composables/useTopbarMenu";
import type { ScopeArgs } from "@/lib/advisorMemoryAdapter";
import type { AdvisorTransport } from "@/lib/advisorTransport";
import type { ProjectCollectionsLoader } from "@/lib/projectCollections";

type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2)
    ? true : false;
type Assert<T extends true> = T;

// Adapter declarations outside this slice must not drift from the public surface.
export type ContractChecks = [
  Assert<Equal<HostActionContext, ActionContext>>,
  Assert<Equal<HostContextualAction, ContextualAction>>,
  Assert<Equal<HostAdvisorScope, ScopeArgs>>,
  Assert<Equal<HostAdvisorTransport, AdvisorTransport>>,
  Assert<Equal<HostConfirmOptions, ConfirmActionOptions>>,
  Assert<Equal<HostMenuItem, TopbarMenuItem>>,
  Assert<Equal<HostPrimaryNavigationItem, PrimaryNavigationItem>>,
  Assert<Equal<HostProjectCollectionsLoader, ProjectCollectionsLoader>>,
  Assert<Equal<CurrentHostContext["api"], AxiosInstance>>,
  Assert<Equal<CurrentHostContext["authStore"]["user"], Ref<HostUser | null>>>,
  Assert<Equal<Awaited<ReturnType<ImportModuleFn>>, ServerModule>>,
  Assert<CurrentHostContext extends HostContext ? true : false>,
];

declare const current: CurrentHostContext;
declare const register: RegisterFn;
export const module: ServerModule = { contextualActionsVersion: 1, register };
void register(current);

// No capability can silently become optional on the host implementation.
declare const missingApi: Omit<CurrentHostContext, "api">;
// @ts-expect-error The host must provide its full API client.
const incomplete: CurrentHostContext = missingApi;
void incomplete;

// Ref writes, discriminated contexts, and async transport results stay checked.
// @ts-expect-error Identity is a real ref, never an unwrapped value.
current.authStore.user = { id: 1, username: "scientist" };
// @ts-expect-error A deployment action requires its opaque application handle.
const invalidDeploy: HostActionContext = { surface: "deploy", projectId: 1, runId: 2 };
void invalidDeploy;
// @ts-expect-error Confirming a proposal must resolve to a numeric workflow ID.
const invalidConfirm: HostAdvisorTransport["confirmProposal"] = async () => "workflow";
void invalidConfirm;

declare const older: HostContext;
// @ts-expect-error Extensions supporting older hosts must check optional capabilities.
older.confirmAction({ title: "Delete", message: "Delete item", acceptLabel: "Delete" });
