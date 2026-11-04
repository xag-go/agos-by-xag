// Stand-in for next/navigation in web unit tests (scripts/tsx-hooks.mjs): no router, no URL.
const router = {
  push() {},
  replace() {},
  refresh() {},
  back() {},
  forward() {},
  prefetch() {},
};
export const useRouter = () => router;
export const usePathname = () => "/";
export const useSearchParams = () => new URLSearchParams();
export const useParams = () => ({});
export function redirect(to) {
  throw new Error(`redirect ${to}`);
}
export function notFound() {
  throw new Error("not found");
}
