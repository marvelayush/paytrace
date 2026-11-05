"use client";

import { animate, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

/**
 * A number that settles into place on first load (and eases to a new value after a re-run).
 * The final, exact value is always what is rendered once the animation ends, and screen readers
 * only ever get the final value.
 */
export function CountUp({
  value,
  format,
  className,
  duration = 0.7,
}: {
  value: number;
  format: (value: number) => string;
  className?: string;
  duration?: number;
}) {
  const reduceMotion = useReducedMotion();
  const [shown, setShown] = useState(0);
  const from = useRef(0);

  useEffect(() => {
    if (reduceMotion) {
      from.current = value;
      return;
    }
    const controls = animate(from.current, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => setShown(latest),
      onComplete: () => {
        from.current = value;
        setShown(value);
      },
    });
    return () => {
      from.current = value;
      controls.stop();
    };
  }, [value, duration, reduceMotion]);

  return (
    <span className={className}>
      <span aria-hidden>{format(reduceMotion ? value : shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  );
}
