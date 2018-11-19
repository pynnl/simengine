import React from 'react';
import { Image, Group } from 'react-konva';

// ** components
import Asset from '../common/Asset';

// ** misc
import lampSource from '../../../images/lamp.svg';
import lampOffSource from '../../../images/lamp_off.svg';

// import colors from '../../../styles/colors';


/**
 * Outlet Graphics
 */

const SCALE = 0.7;

class Lamp extends Asset {

    constructor(props) {
      super(props);
      this.state = {
        // graphics
        lampImg: null,
        lampOffImg: null,
        backgroundImg: null,
      };
    }

    /** Load Lamp Image */
    componentDidMount() {
      Promise.all(this.loadImages({ lampImg: lampSource, lampOffImg: lampOffSource })).then(() => {
        this.props.onPosChange(this.props.assetId, this.formatAssetCoordinates(this.props));
      });
    }
    
    getInputCoordinates = (center=true) => [
      (center&&this.state.lampImg)?{ x: this.state.lampImg.width*0.5*SCALE, y: this.state.lampImg.height*SCALE, }:{ x: 0, y: 0 }
    ];

    render() {

      const { lampImg, lampOffImg } = this.state;
      // const strokeColor = (this.props.selected) ? colors.selectedAsset: colors.deselectedAsset;

      return(
        <Group x={this.props.x} y={this.props.y} ref="asset" draggable="true" onDragMove={this.updateAssetPos.bind(this)}>
          {/* Outlet Image */}
          <Image image={this.props.asset.status ? lampImg : lampOffImg} onClick={this.handleClick.bind(this)} scale={{x: SCALE, y: SCALE}}/>
        </Group>
      );
    }
}



Lamp.defaultProps = { fontSize: 14, isComponent: true };
export default Lamp;