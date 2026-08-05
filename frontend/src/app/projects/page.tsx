"use client";

import { getProjects } from "@/lib/api/costbook";
import { LotWorkspace } from "@/app/lots/page";

export default function ProjectsPage() {
  return (
    <LotWorkspace
      title="Projects"
      loadingText="Loading projects..."
      emptyText="No projects found"
      loadLots={getProjects}
      showTendering
    />
  );
}
