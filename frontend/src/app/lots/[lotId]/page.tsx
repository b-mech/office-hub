import { redirect } from "next/navigation";

export default async function LotDetailRedirect({
  params,
}: {
  params: Promise<{ lotId: string }>;
}) {
  const { lotId } = await params;
  redirect(`/lots/${lotId}/costbook`);
}
