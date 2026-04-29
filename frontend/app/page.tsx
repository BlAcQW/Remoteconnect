import { redirect } from "next/navigation";
import { cookies } from "next/headers";

export default function Home() {
  const cookieName = process.env.JWT_COOKIE_NAME ?? "rc_jwt";
  const jwt = cookies().get(cookieName);
  redirect(jwt ? "/dashboard" : "/login");
}
