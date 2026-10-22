import AuthPhoto from "@/components/AuthPhoto";
import { X, ArrowSquareOut } from "@phosphor-icons/react";
import { fmtTime, fmtAcc, accClass } from "@/lib/format";

export const PhotoModal = ({ data, onClose }) => {
  if (!data) return null;
  const { record, kind } = data;
  const lat = kind === "in" ? record.check_in_lat : record.check_out_lat;
  const lng = kind === "in" ? record.check_in_lng : record.check_out_lng;
  const acc = kind === "in" ? record.check_in_accuracy : record.check_out_accuracy;
  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm grid place-items-center p-4" onClick={onClose} data-testid="photo-modal">
      <div className="bg-card border border-border max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">{data.label} Photo</div>
            <div className="font-semibold tracking-tight mt-0.5">{record.name}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="close-photo-modal"><X size={18} weight="bold"/></button>
        </div>
        <AuthPhoto path={data.path} className="w-full aspect-[4/3] object-cover bg-black" fallback={<div className="w-full aspect-[4/3] bg-secondary"/>}/>
        <div className="p-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="label-overline mb-1">Timestamp</div>
            <div className="font-mono">{fmtTime(kind === "in" ? record.check_in : record.check_out)}</div>
          </div>
          <div>
            <div className="label-overline mb-1">Face Match</div>
            <div className="font-mono">{kind === "in" ? record.check_in_face_distance : record.check_out_face_distance ?? "—"}</div>
          </div>
          <div>
            <div className="label-overline mb-1">Location</div>
            <div className="font-mono text-xs">{lat?.toFixed(5)}, {lng?.toFixed(5)}</div>
            <a href={`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=18`} target="_blank" rel="noreferrer"
               className="text-[10px] label-overline text-primary hover:underline inline-flex items-center gap-1 mt-1">
              <ArrowSquareOut size={10}/> Open in map
            </a>
          </div>
          <div>
            <div className="label-overline mb-1">GPS Accuracy</div>
            <div className={`font-mono text-xs ${accClass(acc)}`}>{fmtAcc(acc)}</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PhotoModal;
