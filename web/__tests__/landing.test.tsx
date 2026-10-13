import { render, screen } from "@testing-library/react";
import LandingPage from "@/app/page";

jest.mock("@clerk/nextjs", () => ({
  useUser: () => ({ isSignedIn: false }),
  SignInButton: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  UserButton: () => null,
}));

describe("Landing page", () => {
  it("renders the hero heading", () => {
    render(<LandingPage />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toMatch(/Knowledge Base/i);
    expect(h1.textContent).toMatch(/Cites Its Sources/i);
  });

  it("renders the Get started link pointing to /docs", () => {
    render(<LandingPage />);
    const link = screen.getByRole("link", { name: /get started/i });
    expect(link).toHaveAttribute("href", "/docs");
  });

  it("renders all feature cards", () => {
    render(<LandingPage />);
    expect(screen.getByText("Multi-Agent Pipeline")).toBeInTheDocument();
    expect(screen.getByText("Researcher Tools")).toBeInTheDocument();
    expect(screen.getByText("Hybrid Search")).toBeInTheDocument();
    expect(screen.getByText("RAGAS Evaluation")).toBeInTheDocument();
    expect(screen.getByText("Semantic Cache")).toBeInTheDocument();
    expect(screen.getByText("MCP Server")).toBeInTheDocument();
  });
});
