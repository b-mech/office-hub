"use client";

import { getProjects } from "@/lib/api/costbook";
import { LotWorkspace } from "@/components/lots/LotWorkspace";

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
