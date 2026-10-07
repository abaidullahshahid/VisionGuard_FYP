import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "./Icons";

// Styled replacement for <select>: the native option popup cannot be themed
// (white background, OS hover colors), so the list is rendered here instead.
// options: [{ value, label, description? }]
export default function SelectMenu({
  id,
  value,
  options,
  onChange,
  placeholder = "Select...",
  disabled = false,
  ariaLabel,
  className = "",
}) {
  const listId = useId();
  const rootRef = useRef(null);
  const listRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [dropUp, setDropUp] = useState(false);
  const selectedIndex = options.findIndex((option) => String(option.value) === String(value));
  const selected = options[selectedIndex];

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutsideClick = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  useEffect(() => {
    if (open) listRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const openList = () => {
    if (disabled) return;
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    // Open upwards when the list would not fit below the control.
    const rect = rootRef.current?.getBoundingClientRect();
    if (rect && window.innerHeight) {
      const listHeight = Math.min(300, options.length * 40 + 14);
      const below = window.innerHeight - rect.bottom;
      setDropUp(below < listHeight + 12 && rect.top > below);
    }
    setOpen(true);
  };

  const choose = (index) => {
    const option = options[index];
    if (option) onChange(option.value);
    setOpen(false);
    rootRef.current?.querySelector("button")?.focus();
  };

  const handleButtonKeyDown = (event) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      openList();
    }
  };

  const handleListKeyDown = (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((index) => (index + step + options.length) % options.length);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(activeIndex);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      rootRef.current?.querySelector("button")?.focus();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  };

  return (
    <div className={`select-menu${open ? " open" : ""}${dropUp ? " drop-up" : ""}${disabled ? " disabled" : ""}${className ? ` ${className}` : ""}`} ref={rootRef}>
      <button
        id={id}
        type="button"
        className="form-input select-menu-button"
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={handleButtonKeyDown}
      >
        <span className={`select-menu-value${selected ? "" : " placeholder"}`}>
          {selected ? selected.label : placeholder}
        </span>
        <span className="select-menu-chevron" aria-hidden="true" />
      </button>
      {open && (
        <ul
          id={listId}
          ref={listRef}
          className="select-menu-list"
          role="listbox"
          tabIndex={-1}
          aria-labelledby={ariaLabel ? undefined : id}
          aria-label={ariaLabel}
          aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
          onKeyDown={handleListKeyDown}
        >
          {options.map((option, index) => {
            const isSelected = index === selectedIndex;
            return (
              <li
                key={String(option.value)}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={isSelected}
                className={`select-menu-option${index === activeIndex ? " active" : ""}${isSelected ? " selected" : ""}`}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(index)}
              >
                <span className="select-menu-option-copy">
                  <span className="select-menu-option-label">{option.label}</span>
                  {option.description && <span className="select-menu-option-description">{option.description}</span>}
                </span>
                {isSelected && <Icon name="check" size={15} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
