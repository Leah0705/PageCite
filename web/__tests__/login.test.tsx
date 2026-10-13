import { render, screen } from "@testing-library/react";
import LoginPage from "@/app/login/page";

jest.mock("@clerk/nextjs", () => ({
  SignIn: () => <div data-testid="clerk-sign-in" />,
  useUser: () => ({ isSignedIn: false }),
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/login",
}));

jest.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
}));

describe("Login page", () => {
  it("renders the PageCite logo link", () => {
    render(<LoginPage />);
    expect(screen.getByRole("link", { name: /pagecite/i })).toHaveAttribute("href", "/");
  });

  it("renders the Clerk sign-in component", () => {
    render(<LoginPage />);
    expect(screen.getByTestId("clerk-sign-in")).toBeInTheDocument();
  });
});
