import {
  HubConnection,
  HubConnectionBuilder,
  HubConnectionState,
  LogLevel,
} from "@microsoft/signalr";
import type { Message } from "./api";

export type RealtimeNotification =
  | {
      type: "message";
      conversationId: string;
      itemId: string;
      senderUserId: string;
      message: Message;
    }
  | {
      type: "claim_created";
      claimId: string;
      itemId: string;
      claimantUserId: string;
    }
  | {
      type: "claim_decided";
      claimId: string;
      itemId: string;
      decision: "approved" | "rejected";
      conversationId?: string | null;
    }
  | {
      type: "item_returned";
      itemId: string;
      claimId?: string | null;
    };

let connection: HubConnection | null = null;
let connectingPromise: Promise<HubConnection> | null = null;

export async function getChatHubConnection(): Promise<HubConnection> {
  if (connection && connection.state === HubConnectionState.Connected) {
    return connection;
  }
  if (connectingPromise) {
    return connectingPromise;
  }

  const newConnection = new HubConnectionBuilder()
    .withUrl("/hubs/chat")
    .withAutomaticReconnect([0, 2000, 5000, 10000, 30000])
    .configureLogging(LogLevel.Warning)
    .build();

  connectingPromise = newConnection
    .start()
    .then(() => {
      connection = newConnection;
      connectingPromise = null;
      return newConnection;
    })
    .catch((cause) => {
      connectingPromise = null;
      throw cause;
    });

  return connectingPromise;
}

export async function joinConversation(conversationId: string): Promise<void> {
  try {
    const conn = await getChatHubConnection();
    await conn.invoke("JoinConversation", conversationId);
  } catch {
    // Non-blocking if websocket connection drops or not ready
  }
}

export async function leaveConversation(conversationId: string): Promise<void> {
  try {
    const conn = await getChatHubConnection();
    await conn.invoke("LeaveConversation", conversationId);
  } catch {
    // Non-blocking
  }
}
