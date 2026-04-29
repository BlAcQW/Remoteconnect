export type Machine = {
  id: string;
  name: string;
  hostname: string | null;
  os: string | null;
  ip_address: string | null;
  last_seen: string | null;
  is_online: boolean;
  created_at: string;
};

export type Session = {
  id: string;
  machine_id: string;
  technician_id: string;
  daily_room_url: string | null;
  daily_room_name: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  meeting_token?: string | null;
};

export type MeetingToken = {
  room_url: string;
  room_name: string | null;
  token: string | null;
  role: "technician" | "agent";
};

export type Me = {
  id: string;
  email: string;
  role: string;
};
