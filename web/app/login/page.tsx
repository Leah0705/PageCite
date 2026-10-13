"use client";

import { SignIn } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import { motion } from "framer-motion";
import Nav from "@/components/nav";

export default function LoginPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Nav />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% -5%, oklch(0.62 0.22 264 / 0.12), transparent)",
        }}
      />

      <main className="flex-1 flex flex-col items-center justify-center px-4 py-12">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          <SignIn
            routing="hash"
            appearance={{
              baseTheme: dark,
              variables: {
                colorPrimary: "oklch(0.62 0.22 264)",
              },
            }}
          />
        </motion.div>
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} PageCite
      </footer>
    </div>
  );
}
