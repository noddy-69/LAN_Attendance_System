export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: string | null;
  pagination: PaginationMeta | null;
}

export interface PaginationMeta {
  total: number;
  page: number;
  per_page: number;
  has_next: boolean;
  next_cursor: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}
