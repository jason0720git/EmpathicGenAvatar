// Detect sustained foreground presentation stalls, not isolated startup frames.
export class PerceptionResponsiveness {
  private previous:number|null=null
  private warmUntil=0
  private stalls:number[]=[]
  sample(now:number,visible:boolean):boolean {
    if(!visible||this.previous===null){this.previous=now;this.warmUntil=now+4000;this.stalls=[];return false}
    const gap=now-this.previous;this.previous=now
    if(now<this.warmUntil)return false
    this.stalls=this.stalls.filter(t=>now-t<5000)
    if(gap>250)this.stalls.push(now)
    return this.stalls.length>=4
  }
}
