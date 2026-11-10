"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
export default function PublicMaintenanceShell({children,publicContent}:{children:ReactNode;publicContent:ReactNode}){
  const pathname=usePathname();
  return pathname.startsWith("/r/")||pathname.startsWith("/w/") ? <div className="min-h-screen">{publicContent}</div> : <>{children}</>;
}
