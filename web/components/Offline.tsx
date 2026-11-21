export default function Offline({ message }: { message?: string }) {
  return (
    <div className="notice">
      <h2>The edge service isn&apos;t responding</h2>
      <p>
        {message ?? "The dashboard couldn't load data."} Start it with <code>uv run observatory serve</code> in{" "}
        <code>edge/</code>, or check the Pi with <code>docker compose ps</code>.
      </p>
    </div>
  );
}
