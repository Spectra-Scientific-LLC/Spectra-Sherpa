import axios from "axios";

interface ErrorBody {
  detail?: string;
  message?: string;
  error?: string;
}

export function getErrorMessage(
  error: unknown,
  fallback = "An unexpected error occurred",
): string {
  if (axios.isAxiosError<ErrorBody>(error)) {
    return (
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.response?.data?.error ||
      error.message ||
      fallback
    );
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  if (typeof error === "string") {
    return error;
  }

  return fallback;
}
