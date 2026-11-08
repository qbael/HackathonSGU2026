import { useCallback, useEffect, useState } from "react";
import { api, type NotificationSummary } from "../lib/api";
import { getChatHubConnection, type RealtimeNotification } from "../lib/realtime";
import type { UserProfile } from "../lib/auth";

export function useNotifications(user: UserProfile | null, activeConversationId?: string | null) {
  const [unreadByConversation, setUnreadByConversation] = useState<Record<string, number>>({});
  const [pendingRequestsCount, setPendingRequestsCount] = useState<number>(0);
  const [decidedRequestsCount, setDecidedRequestsCount] = useState<number>(0);

  const totalUnreadMessages = Object.values(unreadByConversation).reduce(
    (acc, count) => acc + count,
    0,
  );

  const markConversationRead = useCallback(
    (conversationId: string, latestSeq?: number) => {
      setUnreadByConversation((prev) => {
        if (!prev[conversationId]) return prev;
        const next = { ...prev };
        delete next[conversationId];
        return next;
      });
      if (typeof latestSeq === "number") {
        try {
          localStorage.setItem(`findie_read_seq_${conversationId}`, String(latestSeq));
        } catch {
          // ignore storage error
        }
      }
    },
    [],
  );

  const markRequestsSeen = useCallback(() => {
    setPendingRequestsCount(0);
    try {
      localStorage.setItem("findie_last_requests_seen", new Date().toISOString());
    } catch {
      // ignore
    }
  }, []);

  const refreshSummary = useCallback(async () => {
    if (!user) return;
    try {
      const summary = await api<NotificationSummary>("/api/notifications/summary");
      setPendingRequestsCount(summary.pendingRequestsCount);
      setDecidedRequestsCount(summary.decidedRequestsCount);

      const unreadMap: Record<string, number> = {};
      for (const conv of summary.conversations) {
        if (conv.id === activeConversationId) continue;
        const saved = localStorage.getItem(`findie_read_seq_${conv.id}`);
        const savedSeq = saved ? Number(saved) : 0;
        if (conv.latestSequence > savedSeq && conv.latestSenderUserId !== user.id) {
          unreadMap[conv.id] = Math.max(1, conv.latestSequence - savedSeq);
        }
      }
      setUnreadByConversation(unreadMap);
    } catch {
      // ignore offline/abort
    }
  }, [user, activeConversationId]);

  useEffect(() => {
    if (!user) {
      setUnreadByConversation({});
      setPendingRequestsCount(0);
      setDecidedRequestsCount(0);
      return;
    }

    void refreshSummary();

    let active = true;
    let removeListener: (() => void) | null = null;

    getChatHubConnection()
      .then((conn) => {
        if (!active) return;

        const handleNotification = (notif: RealtimeNotification) => {
          if (!active) return;
          if (notif.type === "message") {
            if (notif.conversationId === activeConversationId) {
              // Current chat is open, automatically mark read
              try {
                localStorage.setItem(
                  `findie_read_seq_${notif.conversationId}`,
                  String(notif.message.sequence),
                );
              } catch {
                // ignore
              }
              return;
            }

            setUnreadByConversation((prev) => ({
              ...prev,
              [notif.conversationId]: (prev[notif.conversationId] ?? 0) + 1,
            }));
          } else if (notif.type === "claim_created") {
            setPendingRequestsCount((prev) => prev + 1);
          } else if (notif.type === "claim_decided") {
            setPendingRequestsCount((prev) => prev + 1);
          }
        };

        conn.on("NotificationReceived", handleNotification);
        removeListener = () => conn.off("NotificationReceived", handleNotification);
      })
      .catch(() => {
        // Fallback to polling refresh if websocket is unavailable
      });

    return () => {
      active = false;
      if (removeListener) removeListener();
    };
  }, [user, activeConversationId, refreshSummary]);

  return {
    unreadMessagesCount: totalUnreadMessages,
    unreadByConversation,
    pendingRequestsCount,
    decidedRequestsCount,
    markConversationRead,
    markRequestsSeen,
    refreshSummary,
  };
}
