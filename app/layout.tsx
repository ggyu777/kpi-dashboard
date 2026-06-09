export const metadata = {
  title: "Running Life | 위클리 KPI",
  description: "Running Life 내부 주간 KPI 대시보드",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
