const nextJest = require("next/jest.js");

const createJestConfig = nextJest({ dir: "./" });

const config = {
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
    "^@clerk/themes$": "<rootDir>/__mocks__/@clerk/themes.ts",
  },
  modulePathIgnorePatterns: ["<rootDir>/.next/"],
};

module.exports = createJestConfig(config);
