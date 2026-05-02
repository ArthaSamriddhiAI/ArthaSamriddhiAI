// User identity recovered from a verified application JWT.
//
// Mirror of the backend's UserContext (FR 17.0 §3.1 claim shape). Kept here
// rather than imported from a generated client because cluster 0 hand-writes
// the few API calls it makes; the OpenAPI-generated TypeScript client lands
// in cluster 1.

export type Role = 'advisor' | 'cio' | 'compliance' | 'audit'

export interface User {
  user_id: string
  firm_id: string
  role: Role
  email: string
  name: string
  session_id: string
}

export interface JWTClaims {
  sub: string
  firm_id: string
  role: Role
  email: string
  name: string
  session_id: string
  iat: number
  exp: number
  iss: string
  aud: string
}
