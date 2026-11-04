import { ButtonLink } from "@/shared/ui/button";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center p-8">
      <div className="max-w-md text-center">
        <h1 className="font-display text-3xl font-semibold">Page not found</h1>
        <p className="mt-2 text-ink-2">
          This workspace or page doesn&apos;t exist. It may have been renamed,
          archived or deleted.
        </p>
        <ButtonLink href="/" variant="primary" className="mt-6">
          Go home
        </ButtonLink>
      </div>
    </main>
  );
}
