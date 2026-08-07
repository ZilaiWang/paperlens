import { Workbench } from "@/components/Workbench";

export default async function PaperPage({
  params,
}: {
  params: Promise<{ paperId: string }>;
}) {
  const { paperId } = await params;
  return <Workbench paperId={paperId} />;
}
