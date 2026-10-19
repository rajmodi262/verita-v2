import styles from "./KeyboardHelp.module.css";
import { Button, Dialog } from "./ui";

export interface KeyboardHelpProps {
  open: boolean;
  onClose: () => void;
  shortcuts: readonly (readonly [string, string])[];
}

export function KeyboardHelp({ open, onClose, shortcuts }: KeyboardHelpProps) {
  return (
    <Dialog
      title="Keyboard shortcuts"
      open={open}
      onClose={onClose}
      footer={<Button onClick={onClose}>Close</Button>}
    >
      <dl className={styles.list}>
        {shortcuts.map(([key, action]) => (
          <div key={key} className={styles.item}>
            <dt>
              <kbd>{key}</kbd>
            </dt>
            <dd>{action}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
