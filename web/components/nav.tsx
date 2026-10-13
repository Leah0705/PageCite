"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain } from "lucide-react";
import { UserButton, useUser } from "@clerk/nextjs";

import { Button } from "@/components/ui/button";

const links = [
  { href: "/",                    label: "Home",       external: false },
  { href: "/docs",                label: "Documents",  external: false },
  { href: "/chat",                label: "Chat",       external: false },
  { href: "/usage",               label: "Usage",      external: false },
  { href: "/api-keys",            label: "API Keys",   external: false },
  { href: "/how-to-use",          label: "How to Use", external: false },
  { href: "/about",               label: "About",      external: false },
];

export default function Nav() {
  const path = usePathname();
  const { isSignedIn } = useUser();

  return (
    <header className="border-b border-border bg-background/70 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight group">
          <Brain className="size-6 text-primary transition-transform duration-300 group-hover:scale-110" />
          <span>PageCite</span>
        </Link>

        <nav className="flex items-center gap-0.5">
          {links.map(({ href, label, external }) =>
            external ? (
              <a
                key={href}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 rounded-md text-sm transition-colors text-muted-foreground hover:text-foreground hover:bg-accent/50"
              >
                {label}
              </a>
            ) : (
              <Link
                key={href}
                href={href}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  (href === "/" ? path === "/" : path.startsWith(href))
                    ? "bg-primary/15 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                }`}
              >
                {label}
              </Link>
            )
          )}

          <div className="ml-2 flex items-center">
            {isSignedIn ? (
              <UserButton appearance={{ elements: { avatarBox: "size-8" } }} />
            ) : (
              <Link href="/login">
                <Button size="sm" variant="outline">Sign in</Button>
              </Link>
            )}
          </div>
        </nav>
      </div>
    </header>
  );
}
