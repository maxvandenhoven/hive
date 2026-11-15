import { CameraIcon, Loader2Icon } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";

interface CameraCaptureProps {
  /** Called with the photo once one is taken or picked. */
  onCapture: (image: File) => void;
  disabled?: boolean;
  /** Whether a photo is being read, which shows a spinner. */
  busy?: boolean;
  label?: string;
  variant?: "default" | "outline";
  size?: "default" | "sm" | "lg";
}

/**
 * The camera button: opens the phone camera (the back one, `capture="environment"`), or
 * a file picker on a desktop, and hands the photo on.
 */
export function CameraCapture({
  onCapture,
  disabled = false,
  busy = false,
  label = "Photo",
  variant = "outline",
  size = "default",
}: CameraCaptureProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        aria-label={`${label} of the board`}
        className="sr-only"
        tabIndex={-1}
        onChange={(event) => {
          const image = event.target.files?.[0];
          // Clear the input, so the same file can be picked again.
          event.target.value = "";

          if (image !== undefined) {
            onCapture(image);
          }
        }}
      />
      <Button
        type="button"
        variant={variant}
        size={size}
        disabled={disabled || busy}
        onClick={() => {
          inputRef.current?.click();
        }}
      >
        {busy ? <Loader2Icon className="animate-spin" /> : <CameraIcon />}
        {label}
      </Button>
    </>
  );
}
