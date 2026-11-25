"use client";

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light";

const ThemeContext = createContext({
  theme: "dark" as Theme,
  setTheme: (_theme: Theme) => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const saved = window.localStorage.getItem("pylake-theme");
    const initial: Theme = saved === "light" ? "light" : "dark";
    const timeout = window.setTimeout(() => {
      setTheme(initial);
      document.documentElement.dataset.theme = initial;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, []);

  const updateTheme = (next: Theme) => {
    setTheme(next);
    window.localStorage.setItem("pylake-theme", next);
    document.documentElement.dataset.theme = next;
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme: updateTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
