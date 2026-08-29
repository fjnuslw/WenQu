import { ChatRoom } from "@/components/interview/chat-room";

export default async function InterviewRoomPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ChatRoom sessionId={id} />;
}
