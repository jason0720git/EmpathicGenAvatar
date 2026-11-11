import type { WireEvent } from './types'

type Run = {key:string;id:Promise<string>;events:WireEvent[];expires:number;flushing:boolean;closed:boolean;saved:number;dropped:number;sequence:number}
export type PreviewStatus = {id?:string; state:'recording'|'saved'|'error'; saved:number; dropped:number; error?:string}

/** Separate idle UI experiments; never open an audio/Realtime websocket to log a slider. */
export class PreviewCapture {
  private run?:Run
  private latest?:Run
  constructor(private create:(avatar:string)=>Promise<string>,private post:(id:string,events:WireEvent[])=>Promise<void>,private status:(s:PreviewStatus)=>void){}
  active(){return !!this.run}
  start(key:string,now:number,event:WireEvent) {
    if(this.run && (key!==this.run.key || now>=this.run.expires)) this.finish()
    if(!this.run) {
      const run:Run={key,id:this.create(key),events:[],expires:0,flushing:false,closed:false,saved:0,dropped:0,sequence:0}
      this.run=run;this.latest=run
      run.id.then(id=>{if(this.latest===run)this.status({id,state:'recording',saved:0,dropped:0})}).catch(err=>{
        if(this.run===run)this.run=undefined
        if(this.latest===run)this.status({state:'error',saved:0,dropped:run.dropped+run.events.length,error:String(err)})
      })
    }
    this.run.expires=now+6000;this.add(event)
  }
  add(event:WireEvent){
    const run=this.run;if(!run)return
    // Keep user actions when a sample batch is already delayed.
    if(run.events.length>=64){const i=run.events.findIndex(e=>e.event==='motion.sample');if(i>=0)run.events.splice(i,1);else run.events.shift();run.dropped++}
    run.events.push({...event,preview_seq:++run.sequence})
  }
  tick(now:number){
    const run=this.run;if(!run)return
    if(now>=run.expires)this.finish()
    else if(run.events.length>=5)void this.flush(run)
  }
  finish(){
    const run=this.run;if(!run)return
    this.run=undefined;run.closed=true;void this.flush(run)
  }
  private async flush(run:Run){
    if(run.flushing)return
    run.flushing=true
    try{
      const id=await run.id
      while(run.events.length){
        const batch=run.events.splice(0,5)
        try{await this.post(id,batch);run.saved+=batch.length}
        catch(error){run.dropped+=batch.length+run.events.length;run.events=[];if(this.run===run)this.run=undefined
          if(this.latest===run)this.status({id,state:'error',saved:run.saved,dropped:run.dropped,error:String(error)});return}
        if(!run.closed)break
      }
      if(this.latest===run)this.status({id,state:run.closed?'saved':'recording',saved:run.saved,dropped:run.dropped})
    }catch{/* Create failure is reported by start(). */}
    finally{run.flushing=false}
  }
}
